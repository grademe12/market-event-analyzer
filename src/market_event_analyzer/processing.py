from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import json
from pathlib import Path
import sqlite3
from typing import Protocol

from market_event_analyzer.classification import (
    ClassificationInput,
    EventType,
)
from market_event_analyzer.composition import compose_market_event
from market_event_analyzer.contract import Direction, Impact, MarketEvent
from market_event_analyzer.interfaces import (
    DisclosureEnricher,
    EventAssessmentModel,
    NewsCollector,
)
from market_event_analyzer.news import RawNewsItem


Clock = Callable[[], datetime]


class EventTypeNormalizer(Protocol):
    def normalize(self, provider_event_name: str) -> EventType: ...


class ProcessingState(StrEnum):
    DISCOVERED = "DISCOVERED"
    ENRICHED = "ENRICHED"
    CLASSIFIED = "CLASSIFIED"
    DELIVERED = "DELIVERED"


@dataclass(frozen=True, slots=True)
class ProcessingRecord:
    state: ProcessingState
    item: RawNewsItem
    event_type: EventType | None
    attempt_count: int
    last_error: str
    event: MarketEvent | None = None


@dataclass(frozen=True, slots=True)
class ProcessingFailure:
    provider: str
    provider_item_id: str
    state: ProcessingState
    error: str


@dataclass(frozen=True, slots=True)
class ProcessingCycleResult:
    collected_count: int
    discovered_count: int
    enriched_count: int
    classified_count: int
    failed_count: int
    events: tuple[MarketEvent, ...]
    failures: tuple[ProcessingFailure, ...]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SQLiteProcessingStore:
    """Durable state for retryable analysis and downstream delivery."""

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Clock = _utc_now,
    ) -> None:
        self._path = Path(path)
        self._clock = clock
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self._path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_items (
                    provider TEXT NOT NULL,
                    provider_item_id TEXT NOT NULL,
                    first_detected_at TEXT NOT NULL,
                    processing_state TEXT NOT NULL,
                    item_json TEXT NOT NULL,
                    event_type TEXT,
                    event_json TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (provider, provider_item_id)
                )
                """
            )

    def discover(self, items: tuple[RawNewsItem, ...]) -> int:
        discovered = 0
        with self._connect() as connection:
            for item in items:
                now = self._now_iso()
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO analysis_items (
                        provider,
                        provider_item_id,
                        first_detected_at,
                        processing_state,
                        item_json,
                        event_type,
                        event_json,
                        attempt_count,
                        last_error,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, NULL, NULL, 0, '', ?)
                    """,
                    (
                        item.provider,
                        item.provider_item_id,
                        item.detected_at.isoformat(),
                        ProcessingState.DISCOVERED.value,
                        _serialize_item(item),
                        now,
                    ),
                )
                discovered += cursor.rowcount
        return discovered

    def pending(self) -> tuple[ProcessingRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM analysis_items
                WHERE processing_state IN (?, ?)
                ORDER BY first_detected_at, provider, provider_item_id
                """,
                (
                    ProcessingState.DISCOVERED.value,
                    ProcessingState.ENRICHED.value,
                ),
            ).fetchall()
        return tuple(_record_from_row(row) for row in rows)

    def get_record(
        self,
        provider: str,
        provider_item_id: str,
    ) -> ProcessingRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM analysis_items
                WHERE provider = ? AND provider_item_id = ?
                """,
                (provider, provider_item_id),
            ).fetchone()
        return _record_from_row(row) if row is not None else None

    def mark_enriched(
        self,
        item: RawNewsItem,
        event_type: EventType,
    ) -> None:
        self._transition(
            item,
            expected=ProcessingState.DISCOVERED,
            target=ProcessingState.ENRICHED,
            event_type=event_type,
            event=None,
        )

    def mark_classified(
        self,
        item: RawNewsItem,
        event: MarketEvent,
    ) -> None:
        self._transition(
            item,
            expected=ProcessingState.ENRICHED,
            target=ProcessingState.CLASSIFIED,
            event_type=None,
            event=event,
        )

    def mark_delivered(self, item: RawNewsItem) -> None:
        self._transition(
            item,
            expected=ProcessingState.CLASSIFIED,
            target=ProcessingState.DELIVERED,
            event_type=None,
            event=None,
        )

    def record_failure(
        self,
        item: RawNewsItem,
        error: Exception,
    ) -> ProcessingFailure:
        message = f"{type(error).__name__}: {error}".strip()
        message = message[:1000]
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT processing_state
                FROM analysis_items
                WHERE provider = ? AND provider_item_id = ?
                """,
                (item.provider, item.provider_item_id),
            ).fetchone()
            if row is None:
                raise KeyError("processing item does not exist")
            state = ProcessingState(str(row["processing_state"]))
            connection.execute(
                """
                UPDATE analysis_items
                SET attempt_count = attempt_count + 1,
                    last_error = ?,
                    updated_at = ?
                WHERE provider = ? AND provider_item_id = ?
                """,
                (
                    message,
                    self._now_iso(),
                    item.provider,
                    item.provider_item_id,
                ),
            )
        return ProcessingFailure(
            provider=item.provider,
            provider_item_id=item.provider_item_id,
            state=state,
            error=message,
        )

    def classified_records(self) -> tuple[ProcessingRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM analysis_items
                WHERE processing_state = ?
                ORDER BY first_detected_at, provider, provider_item_id
                """,
                (ProcessingState.CLASSIFIED.value,),
            ).fetchall()
        return tuple(_record_from_row(row) for row in rows)

    def classified_events(self) -> tuple[MarketEvent, ...]:
        return tuple(
            record.event
            for record in self.classified_records()
            if record.event is not None
        )

    def _transition(
        self,
        item: RawNewsItem,
        *,
        expected: ProcessingState,
        target: ProcessingState,
        event_type: EventType | None,
        event: MarketEvent | None,
    ) -> None:
        assignments = [
            "processing_state = ?",
            "item_json = ?",
            "last_error = ''",
            "updated_at = ?",
        ]
        values: list[object] = [
            target.value,
            _serialize_item(item),
            self._now_iso(),
        ]
        if event_type is not None:
            assignments.append("event_type = ?")
            values.append(event_type.value)
        if event is not None:
            assignments.append("event_json = ?")
            values.append(
                json.dumps(
                    event.to_payload(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )

        values.extend(
            [
                item.provider,
                item.provider_item_id,
                expected.value,
            ]
        )
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE analysis_items
                SET {", ".join(assignments)}
                WHERE provider = ?
                  AND provider_item_id = ?
                  AND processing_state = ?
                """,
                values,
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"invalid processing transition {expected.value} -> {target.value}"
                )

    def _now_iso(self) -> str:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("processing store clock must be timezone-aware")
        return now.isoformat()


class DurableAnalysisPipeline:
    """Collect new items and retry stored work until a MarketEvent is classified."""

    def __init__(
        self,
        collector: NewsCollector,
        enricher: DisclosureEnricher,
        normalizer: EventTypeNormalizer,
        model: EventAssessmentModel,
        store: SQLiteProcessingStore,
    ) -> None:
        self._collector = collector
        self._enricher = enricher
        self._normalizer = normalizer
        self._model = model
        self._store = store

    def run_once(self) -> ProcessingCycleResult:
        collected = self._collector.collect()
        discovered_count = self._store.discover(collected)
        enriched_count = 0
        classified_count = 0
        events: list[MarketEvent] = []
        failures: list[ProcessingFailure] = []

        for record in self._store.pending():
            item = record.item
            event_type = record.event_type

            if record.state is ProcessingState.DISCOVERED:
                try:
                    item = self._enricher.enrich(item)
                    event_type = self._normalizer.normalize(
                        item.provider_event_name
                    )
                    self._store.mark_enriched(item, event_type)
                    enriched_count += 1
                except Exception as exc:
                    failures.append(self._store.record_failure(item, exc))
                    continue

            if event_type is None:
                failures.append(
                    self._store.record_failure(
                        item,
                        RuntimeError("enriched item is missing event type"),
                    )
                )
                continue

            try:
                symbol = _single_symbol(item)
                decision = self._model.assess(
                    ClassificationInput(
                        symbol=symbol,
                        event_type=event_type,
                        headline=item.headline,
                        body=item.body,
                        source=item.provider,
                        source_item_id=item.provider_item_id,
                        provider_event_name=item.provider_event_name,
                    )
                )
                event = compose_market_event(
                    item,
                    event_type,
                    decision,
                    symbol=symbol,
                )
                self._store.mark_classified(item, event)
                classified_count += 1
                events.append(event)
            except Exception as exc:
                failures.append(self._store.record_failure(item, exc))

        return ProcessingCycleResult(
            collected_count=len(collected),
            discovered_count=discovered_count,
            enriched_count=enriched_count,
            classified_count=classified_count,
            failed_count=len(failures),
            events=tuple(events),
            failures=tuple(failures),
        )


def _single_symbol(item: RawNewsItem) -> str:
    if len(item.symbols) != 1:
        raise ValueError(
            "durable analysis currently requires exactly one symbol per item"
        )
    return item.symbols[0]


def _serialize_item(item: RawNewsItem) -> str:
    payload = {
        "provider": item.provider,
        "provider_item_id": item.provider_item_id,
        "headline": item.headline,
        "detected_at": item.detected_at.isoformat(),
        "published_at": (
            item.published_at.isoformat()
            if item.published_at is not None
            else None
        ),
        "body": item.body,
        "url": item.url,
        "symbols": list(item.symbols),
        "provider_event_name": item.provider_event_name,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _deserialize_item(payload: str) -> RawNewsItem:
    raw = json.loads(payload)
    published_at = raw.get("published_at")
    return RawNewsItem(
        provider=str(raw["provider"]),
        provider_item_id=str(raw["provider_item_id"]),
        headline=str(raw["headline"]),
        detected_at=datetime.fromisoformat(str(raw["detected_at"])),
        published_at=(
            datetime.fromisoformat(str(published_at))
            if published_at is not None
            else None
        ),
        body=str(raw.get("body", "")),
        url=str(raw.get("url", "")),
        symbols=tuple(str(value) for value in raw.get("symbols", [])),
        provider_event_name=str(raw.get("provider_event_name", "")),
    )


def _deserialize_event(payload: str) -> MarketEvent:
    raw = json.loads(payload)
    occurred_at = raw.get("occurred_at")
    return MarketEvent(
        event_id=str(raw["event_id"]),
        symbol=str(raw["symbol"]),
        event_type=str(raw["event_type"]),
        direction=Direction(str(raw["direction"])),
        confidence=float(raw["confidence"]),
        impact=Impact(str(raw["impact"])),
        occurred_at=(
            datetime.fromisoformat(str(occurred_at))
            if occurred_at is not None
            else None
        ),
        detected_at=datetime.fromisoformat(str(raw["detected_at"])),
        source=str(raw["source"]),
        source_item_id=str(raw.get("source_item_id", "")),
        headline=str(raw.get("headline", "")),
    )


def _record_from_row(row: sqlite3.Row) -> ProcessingRecord:
    raw_event_type = row["event_type"]
    return ProcessingRecord(
        state=ProcessingState(str(row["processing_state"])),
        item=_deserialize_item(str(row["item_json"])),
        event_type=(
            EventType(str(raw_event_type))
            if raw_event_type is not None
            else None
        ),
        attempt_count=int(row["attempt_count"]),
        last_error=str(row["last_error"]),
        event=(
            _deserialize_event(str(row["event_json"]))
            if row["event_json"] is not None
            else None
        ),
    )
