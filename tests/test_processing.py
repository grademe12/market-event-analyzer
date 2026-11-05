from datetime import datetime, timezone

from market_event_analyzer.classification import (
    ClassificationDecision,
    EventType,
)
from market_event_analyzer.contract import Direction, Impact
from market_event_analyzer.news import RawNewsItem
from market_event_analyzer.processing import (
    DurableAnalysisPipeline,
    ProcessingState,
    SQLiteProcessingStore,
)


NOW = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)


def make_item(item_id: str = "20260928000123") -> RawNewsItem:
    return RawNewsItem(
        provider="opendart",
        provider_item_id=item_id,
        headline="삼성전자: 단일판매ㆍ공급계약체결",
        detected_at=NOW,
        body="",
        symbols=("005930",),
        provider_event_name="단일판매ㆍ공급계약체결",
    )


class FakeCollector:
    def __init__(self, batches):
        self._batches = list(batches)

    def collect(self):
        if self._batches:
            return self._batches.pop(0)
        return ()


class FlakyEnricher:
    def __init__(self):
        self.calls = 0

    def enrich(self, item):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary document failure")
        return RawNewsItem(
            provider=item.provider,
            provider_item_id=item.provider_item_id,
            headline=item.headline,
            detected_at=item.detected_at,
            published_at=item.published_at,
            body="계약금액은 최근 매출액 대비 18.4% 규모다.",
            url=item.url,
            symbols=item.symbols,
            provider_event_name=item.provider_event_name,
        )


class FakeNormalizer:
    def normalize(self, provider_event_name):
        return EventType.SUPPLY_CONTRACT


class FlakyModel:
    def __init__(self):
        self.calls = 0

    def assess(self, item):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary model failure")
        return ClassificationDecision(
            direction=Direction.BUY,
            impact=Impact.HIGH,
            confidence=0.85,
        )


class StableEnricher:
    def enrich(self, item):
        return RawNewsItem(
            provider=item.provider,
            provider_item_id=item.provider_item_id,
            headline=item.headline,
            detected_at=item.detected_at,
            published_at=item.published_at,
            body="공시 본문",
            url=item.url,
            symbols=item.symbols,
            provider_event_name=item.provider_event_name,
        )


class StableModel:
    def __init__(self):
        self.calls = 0

    def assess(self, item):
        self.calls += 1
        return ClassificationDecision(
            direction=Direction.BUY,
            impact=Impact.HIGH,
            confidence=0.85,
        )


def test_enrichment_failure_remains_retryable_after_collector_stops_returning_item(tmp_path):
    item = make_item()
    enricher = FlakyEnricher()
    store = SQLiteProcessingStore(tmp_path / "processing.sqlite3", clock=lambda: NOW)
    pipeline = DurableAnalysisPipeline(
        FakeCollector([(item,), ()]),
        enricher,
        FakeNormalizer(),
        StableModel(),
        store,
    )

    first = pipeline.run_once()
    assert first.discovered_count == 1
    assert first.failed_count == 1
    assert first.events == ()
    assert store.get_record("opendart", item.provider_item_id).state is ProcessingState.DISCOVERED

    second = pipeline.run_once()
    assert second.collected_count == 0
    assert second.enriched_count == 1
    assert second.classified_count == 1
    assert len(second.events) == 1
    assert store.get_record("opendart", item.provider_item_id).state is ProcessingState.CLASSIFIED


def test_model_failure_retries_from_enriched_without_reenrichment(tmp_path):
    item = make_item()
    model = FlakyModel()

    class CountingEnricher(StableEnricher):
        def __init__(self):
            self.calls = 0

        def enrich(self, item):
            self.calls += 1
            return super().enrich(item)

    enricher = CountingEnricher()
    store = SQLiteProcessingStore(tmp_path / "processing.sqlite3", clock=lambda: NOW)
    pipeline = DurableAnalysisPipeline(
        FakeCollector([(item,), ()]),
        enricher,
        FakeNormalizer(),
        model,
        store,
    )

    first = pipeline.run_once()
    assert first.enriched_count == 1
    assert first.failed_count == 1
    record = store.get_record("opendart", item.provider_item_id)
    assert record.state is ProcessingState.ENRICHED
    assert record.attempt_count == 1

    second = pipeline.run_once()
    assert second.classified_count == 1
    assert enricher.calls == 1
    assert model.calls == 2


def test_classified_event_is_persisted_and_not_reclassified_on_duplicate_discovery(tmp_path):
    item = make_item()
    model = StableModel()
    store = SQLiteProcessingStore(tmp_path / "processing.sqlite3", clock=lambda: NOW)
    pipeline = DurableAnalysisPipeline(
        FakeCollector([(item,), (item,)]),
        StableEnricher(),
        FakeNormalizer(),
        model,
        store,
    )

    first = pipeline.run_once()
    assert first.classified_count == 1
    assert first.events[0].event_id == "opendart:20260928000123:005930"

    second = pipeline.run_once()
    assert second.discovered_count == 0
    assert second.classified_count == 0
    assert second.events == ()
    assert model.calls == 1
    assert store.classified_events()[0].event_id == first.events[0].event_id


def test_classification_logs_disclosure_and_decision(tmp_path, caplog):
    item = make_item()
    store = SQLiteProcessingStore(tmp_path / "processing.sqlite3", clock=lambda: NOW)
    pipeline = DurableAnalysisPipeline(
        FakeCollector([(item,)]),
        StableEnricher(),
        FakeNormalizer(),
        StableModel(),
        store,
    )

    with caplog.at_level("INFO"):
        result = pipeline.run_once()

    assert result.classified_count == 1
    assert "event=disclosure_classified" in caplog.text
    assert "symbol=005930" in caplog.text
    assert "direction=BUY" in caplog.text
    assert "impact=high" in caplog.text
    assert "confidence=0.85" in caplog.text
    assert "headline=삼성전자: 단일판매ㆍ공급계약체결" in caplog.text
    assert "body=공시 본문" in caplog.text


def test_processing_state_survives_store_recreation(tmp_path):
    path = tmp_path / "processing.sqlite3"
    item = make_item()
    first_store = SQLiteProcessingStore(path, clock=lambda: NOW)
    first_store.discover((item,))

    second_store = SQLiteProcessingStore(path, clock=lambda: NOW)
    record = second_store.get_record("opendart", item.provider_item_id)

    assert record is not None
    assert record.state is ProcessingState.DISCOVERED
    assert record.item == item
