from datetime import datetime, timedelta, timezone

import pytest

from market_event_analyzer.contract import Direction, Impact, MarketEvent


def make_event(**overrides) -> MarketEvent:
    occurred_at = datetime(2026, 9, 21, 8, 20, tzinfo=timezone.utc)
    values = {
        "event_id": "news-20260921-0001",
        "symbol": "005930",
        "event_type": "supply_contract",
        "direction": Direction.BUY,
        "confidence": 0.84,
        "impact": Impact.HIGH,
        "occurred_at": occurred_at,
        "detected_at": occurred_at + timedelta(seconds=12),
        "source": "fixture",
        "source_item_id": "provider-123",
        "headline": "Example supply contract announcement",
    }
    values.update(overrides)
    return MarketEvent(**values)


def test_market_event_serializes_to_stable_payload() -> None:
    payload = make_event().to_payload()

    assert payload == {
        "event_id": "news-20260921-0001",
        "symbol": "005930",
        "event_type": "supply_contract",
        "direction": "BUY",
        "confidence": 0.84,
        "impact": "high",
        "occurred_at": "2026-09-21T08:20:00+00:00",
        "detected_at": "2026-09-21T08:20:12+00:00",
        "source": "fixture",
        "source_item_id": "provider-123",
        "headline": "Example supply contract announcement",
    }


@pytest.mark.parametrize("confidence", [-0.01, 1.01, float("inf"), float("nan")])
def test_market_event_rejects_invalid_confidence(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        make_event(confidence=confidence)


def test_market_event_requires_timezone_aware_timestamps() -> None:
    naive = datetime(2026, 9, 21, 8, 20)

    with pytest.raises(ValueError, match="timezone-aware"):
        make_event(occurred_at=naive)


def test_market_event_rejects_detection_before_occurrence() -> None:
    occurred_at = datetime(2026, 9, 21, 8, 20, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="detected_at"):
        make_event(
            occurred_at=occurred_at,
            detected_at=occurred_at - timedelta(seconds=1),
        )
