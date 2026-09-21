from datetime import datetime, timedelta, timezone

from market_event_analyzer.contract import Direction, Impact, MarketEvent
from market_event_analyzer.news import RawNewsItem
from market_event_analyzer.pipeline import AnalysisPipeline


class FakeCollector:
    def __init__(self, items: tuple[RawNewsItem, ...]) -> None:
        self._items = items

    def collect(self) -> tuple[RawNewsItem, ...]:
        return self._items


class FakeClassifier:
    def classify(self, item: RawNewsItem) -> MarketEvent | None:
        if "ignore" in item.headline.lower():
            return None

        return MarketEvent(
            event_id=f"{item.provider}:{item.provider_item_id}",
            symbol="005930",
            event_type="supply_contract",
            direction=Direction.BUY,
            confidence=0.8,
            impact=Impact.HIGH,
            occurred_at=item.published_at,
            detected_at=item.detected_at,
            source=item.provider,
            source_item_id=item.provider_item_id,
            headline=item.headline,
        )


def make_item(item_id: str, headline: str) -> RawNewsItem:
    published_at = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)
    return RawNewsItem(
        provider="fixture",
        provider_item_id=item_id,
        headline=headline,
        body="Example body",
        url=f"https://example.test/{item_id}",
        published_at=published_at,
        detected_at=published_at + timedelta(seconds=2),
    )


def test_pipeline_keeps_collector_and_classifier_separate() -> None:
    collector = FakeCollector(
        (
            make_item("1", "Large supply contract"),
            make_item("2", "Ignore unrelated article"),
        )
    )
    pipeline = AnalysisPipeline(collector, FakeClassifier())

    result = pipeline.run_once()

    assert result.collected_count == 2
    assert result.classified_count == 1
    assert result.ignored_count == 1
    assert len(result.events) == 1
    assert result.events[0].event_id == "fixture:1"
    assert result.events[0].symbol == "005930"


def test_pipeline_returns_no_events_when_collector_is_empty() -> None:
    result = AnalysisPipeline(FakeCollector(()), FakeClassifier()).run_once()

    assert result.collected_count == 0
    assert result.classified_count == 0
    assert result.ignored_count == 0
    assert result.events == ()
