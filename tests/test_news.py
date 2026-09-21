from datetime import datetime, timedelta, timezone

import pytest

from market_event_analyzer.news import RawNewsItem


def test_raw_news_item_allows_unknown_published_at() -> None:
    detected_at = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)

    item = RawNewsItem(
        provider="fixture",
        provider_item_id="item-1",
        headline="Example headline",
        published_at=None,
        detected_at=detected_at,
        symbols=("005930",),
    )

    assert item.published_at is None
    assert item.symbols == ("005930",)


def test_raw_news_item_requires_timezone_aware_detected_at() -> None:
    naive = datetime(2026, 9, 21, 9, 0)

    with pytest.raises(ValueError, match="detected_at"):
        RawNewsItem(
            provider="fixture",
            provider_item_id="item-1",
            headline="Example headline",
            detected_at=naive,
        )


def test_raw_news_item_rejects_detection_before_publication() -> None:
    published_at = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="detected_at"):
        RawNewsItem(
            provider="fixture",
            provider_item_id="item-1",
            headline="Example headline",
            published_at=published_at,
            detected_at=published_at - timedelta(seconds=1),
        )


def test_raw_news_item_rejects_duplicate_symbols() -> None:
    detected_at = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="duplicates"):
        RawNewsItem(
            provider="fixture",
            provider_item_id="item-1",
            headline="Example headline",
            detected_at=detected_at,
            symbols=("005930", "005930"),
        )
