from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Protocol

from market_event_analyzer.classification import EventType
from market_event_analyzer.interfaces import DisclosureEnricher
from market_event_analyzer.news import RawNewsItem
from market_event_analyzer.normalizers import DartEventTypeNormalizer


@dataclass(frozen=True, slots=True)
class DraftEvaluationCase:
    case_id: str
    symbol: str
    event_type: EventType
    headline: str
    body: str
    provider: str
    source_item_id: str
    source_url: str
    provider_event_name: str

    def to_payload(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "symbol": self.symbol,
            "event_type": self.event_type.value,
            "headline": self.headline,
            "body": self.body,
            "provider": self.provider,
            "source_item_id": self.source_item_id,
            "source_url": self.source_url,
            "provider_event_name": self.provider_event_name,
            "acceptable_directions": [],
            "acceptable_impacts": [],
            "review_status": "pending",
        }


@dataclass(frozen=True, slots=True)
class CorpusBuildResult:
    cases: tuple[DraftEvaluationCase, ...]
    attempted_enrichments: int
    failed_enrichments: tuple[str, ...]


class DateRangeCollector(Protocol):
    def collect_range(
        self,
        start_date: date,
        end_date: date,
    ) -> tuple[RawNewsItem, ...]: ...


def build_dart_corpus_candidates(
    collector: DateRangeCollector,
    enricher: DisclosureEnricher,
    *,
    start_date: date,
    end_date: date,
    limit: int = 50,
    max_per_event_type: int = 5,
    include_other: bool = True,
    normalizer: DartEventTypeNormalizer | None = None,
) -> CorpusBuildResult:
    if limit < 1:
        raise ValueError("limit must be positive")
    if max_per_event_type < 1:
        raise ValueError("max_per_event_type must be positive")

    normalizer = normalizer or DartEventTypeNormalizer()
    items = collector.collect_range(start_date, end_date)

    grouped: dict[EventType, list[RawNewsItem]] = {}
    event_type_order: list[EventType] = []
    for item in items:
        event_type = normalizer.normalize(item.provider_event_name)
        if event_type is EventType.OTHER and not include_other:
            continue
        if event_type not in grouped:
            grouped[event_type] = []
            event_type_order.append(event_type)
        grouped[event_type].append(item)

    selected: list[tuple[RawNewsItem, EventType]] = []
    for offset in range(max_per_event_type):
        for event_type in event_type_order:
            bucket = grouped[event_type]
            if offset >= len(bucket):
                continue
            selected.append((bucket[offset], event_type))
            if len(selected) >= limit:
                break
        if len(selected) >= limit:
            break

    cases: list[DraftEvaluationCase] = []
    failures: list[str] = []
    for item, event_type in selected:
        try:
            enriched = enricher.enrich(item)
        except RuntimeError:
            failures.append(item.provider_item_id)
            continue

        if not enriched.symbols:
            failures.append(item.provider_item_id)
            continue

        cases.append(
            DraftEvaluationCase(
                case_id=f"opendart_{enriched.provider_item_id}",
                symbol=enriched.symbols[0],
                event_type=event_type,
                headline=enriched.headline,
                body=enriched.body,
                provider=enriched.provider,
                source_item_id=enriched.provider_item_id,
                source_url=enriched.url,
                provider_event_name=enriched.provider_event_name,
            )
        )

    return CorpusBuildResult(
        cases=tuple(cases),
        attempted_enrichments=len(selected),
        failed_enrichments=tuple(failures),
    )


def write_draft_cases(
    path: str | Path,
    cases: tuple[DraftEvaluationCase, ...],
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for case in cases:
            json.dump(case.to_payload(), handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
