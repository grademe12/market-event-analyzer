from datetime import datetime, timezone

from market_event_analyzer.dedup import (
    DeduplicatingCollector,
    SQLiteSeenItemStore,
)
from market_event_analyzer.news import RawNewsItem


class FakeCollector:
    def __init__(self, batches: list[tuple[RawNewsItem, ...]]) -> None:
        self._batches = batches

    def collect(self) -> tuple[RawNewsItem, ...]:
        return self._batches.pop(0)


def make_item(item_id: str) -> RawNewsItem:
    return RawNewsItem(
        provider="opendart",
        provider_item_id=item_id,
        headline=f"Disclosure {item_id}",
        detected_at=datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc),
        symbols=("005930",),
    )


def test_deduplicating_collector_emits_each_provider_item_once(tmp_path) -> None:
    first = make_item("1")
    second = make_item("2")
    collector = FakeCollector(
        [
            (first,),
            (first, second),
            (first, second),
        ]
    )
    deduped = DeduplicatingCollector(
        collector,
        SQLiteSeenItemStore(tmp_path / "seen.sqlite3"),
    )

    assert deduped.collect() == (first,)
    assert deduped.collect() == (second,)
    assert deduped.collect() == ()


def test_sqlite_seen_state_survives_store_recreation(tmp_path) -> None:
    path = tmp_path / "seen.sqlite3"
    item = make_item("1")

    first_store = SQLiteSeenItemStore(path)
    assert first_store.claim_unseen((item,)) == (item,)

    second_store = SQLiteSeenItemStore(path)
    assert second_store.claim_unseen((item,)) == ()


def test_dedup_key_is_provider_plus_provider_item_id(tmp_path) -> None:
    detected_at = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
    dart_item = RawNewsItem(
        provider="opendart",
        provider_item_id="same-id",
        headline="DART",
        detected_at=detected_at,
    )
    other_item = RawNewsItem(
        provider="other-provider",
        provider_item_id="same-id",
        headline="Other",
        detected_at=detected_at,
    )

    store = SQLiteSeenItemStore(tmp_path / "seen.sqlite3")

    assert store.claim_unseen((dart_item, other_item)) == (dart_item, other_item)
