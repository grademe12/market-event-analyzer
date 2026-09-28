from collections.abc import Callable
from dataclasses import dataclass
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from market_event_analyzer.contract import MarketEvent
from market_event_analyzer.processing import (
    ProcessingFailure,
    ProcessingState,
    SQLiteProcessingStore,
)


HttpOpener = Callable[..., object]


class MarketEventDeliveryError(RuntimeError):
    pass


class HttpMarketEventDelivery:
    """Deliver one MarketEvent to the stock-market idempotent ingest endpoint."""

    def __init__(
        self,
        endpoint_url: str,
        *,
        timeout_seconds: float = 10.0,
        open_url: HttpOpener = urlopen,
    ) -> None:
        if not endpoint_url.strip():
            raise ValueError("endpoint_url must not be blank")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._endpoint_url = endpoint_url
        self._timeout_seconds = timeout_seconds
        self._open_url = open_url

    def deliver(self, event: MarketEvent) -> None:
        body = json.dumps(
            event.to_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            self._endpoint_url,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with self._open_url(
                request,
                timeout=self._timeout_seconds,
            ) as response:
                status = int(response.status)
        except HTTPError as exc:
            raise MarketEventDeliveryError(
                f"stock-market rejected event with HTTP {exc.code}"
            ) from exc
        except URLError as exc:
            raise MarketEventDeliveryError(
                f"stock-market delivery failed: {exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise MarketEventDeliveryError(
                "stock-market delivery timed out"
            ) from exc

        if not 200 <= status < 300:
            raise MarketEventDeliveryError(
                f"stock-market returned unexpected HTTP {status}"
            )


@dataclass(frozen=True, slots=True)
class DeliveryCycleResult:
    attempted_count: int
    delivered_count: int
    failed_count: int
    delivered_event_ids: tuple[str, ...]
    failures: tuple[ProcessingFailure, ...]


class DurableDeliveryWorker:
    """Retry classified events without repeating enrichment or model inference."""

    def __init__(
        self,
        store: SQLiteProcessingStore,
        delivery: HttpMarketEventDelivery,
    ) -> None:
        self._store = store
        self._delivery = delivery

    def run_once(self) -> DeliveryCycleResult:
        delivered_event_ids: list[str] = []
        failures: list[ProcessingFailure] = []
        records = self._store.classified_records()

        for record in records:
            if record.state is not ProcessingState.CLASSIFIED:
                continue
            if record.event is None:
                failures.append(
                    self._store.record_failure(
                        record.item,
                        RuntimeError("classified item is missing event payload"),
                    )
                )
                continue

            try:
                self._delivery.deliver(record.event)
                self._store.mark_delivered(record.item)
                delivered_event_ids.append(record.event.event_id)
            except Exception as exc:
                failures.append(self._store.record_failure(record.item, exc))

        return DeliveryCycleResult(
            attempted_count=len(records),
            delivered_count=len(delivered_event_ids),
            failed_count=len(failures),
            delivered_event_ids=tuple(delivered_event_ids),
            failures=tuple(failures),
        )
