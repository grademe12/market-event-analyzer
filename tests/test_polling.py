from datetime import datetime, timezone

from market_event_analyzer.news import RawNewsItem
from market_event_analyzer.polling import CollectorPoller


class FakeCollector:
    def __init__(self) -> None:
        self.calls = 0

    def collect(self) -> tuple[RawNewsItem, ...]:
        self.calls += 1
        return (
            RawNewsItem(
                provider="fixture",
                provider_item_id=str(self.calls),
                headline=f"item {self.calls}",
                detected_at=datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc),
            ),
        )


def test_poller_runs_requested_number_of_cycles() -> None:
    collector = FakeCollector()
    sleeps: list[float] = []
    handled: list[tuple[str, ...]] = []

    poller = CollectorPoller(
        collector,
        interval_seconds=5,
        sleep=sleeps.append,
    )
    poller.run(
        lambda items: handled.append(
            tuple(item.provider_item_id for item in items)
        ),
        max_cycles=3,
    )

    assert collector.calls == 3
    assert handled == [("1",), ("2",), ("3",)]
    assert sleeps == [5, 5]


def test_poller_run_once_returns_cycle_and_items() -> None:
    poller = CollectorPoller(FakeCollector())

    result = poller.run_once(cycle=7)

    assert result.cycle == 7
    assert result.items[0].provider_item_id == "1"
