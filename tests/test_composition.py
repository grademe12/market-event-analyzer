from datetime import datetime, timedelta, timezone

import pytest

from market_event_analyzer.classification import (
    ClassificationDecision,
    EventType,
)
from market_event_analyzer.composition import (
    MarketEventCompositionError,
    compose_market_event,
)
from market_event_analyzer.contract import Direction, Impact
from market_event_analyzer.news import RawNewsItem


def make_item(
    *,
    symbols: tuple[str, ...] = ("005930",),
    published_at: datetime | None = None,
) -> RawNewsItem:
    detected_at = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)
    return RawNewsItem(
        provider="opendart",
        provider_item_id="20260928000123",
        headline="삼성전자 단일판매ㆍ공급계약체결",
        detected_at=detected_at,
        published_at=published_at,
        body="계약금액과 최근 매출액 대비 비율이 포함된 공시 본문",
        symbols=symbols,
        provider_event_name="단일판매ㆍ공급계약체결",
    )


def decision() -> ClassificationDecision:
    return ClassificationDecision(
        direction=Direction.BUY,
        impact=Impact.HIGH,
        confidence=0.85,
    )


def test_compose_market_event_preserves_unknown_occurrence_time() -> None:
    event = compose_market_event(
        make_item(),
        EventType.SUPPLY_CONTRACT,
        decision(),
    )

    assert event.event_id == "opendart:20260928000123:005930"
    assert event.symbol == "005930"
    assert event.event_type == "supply_contract"
    assert event.direction is Direction.BUY
    assert event.impact is Impact.HIGH
    assert event.confidence == pytest.approx(0.85)
    assert event.occurred_at is None
    assert event.detected_at == datetime(
        2026, 9, 28, 9, 0, tzinfo=timezone.utc
    )
    assert event.source == "opendart"
    assert event.source_item_id == "20260928000123"
    assert event.headline == "삼성전자 단일판매ㆍ공급계약체결"


def test_compose_market_event_uses_known_provider_timestamp() -> None:
    occurred_at = datetime(2026, 9, 28, 8, 59, tzinfo=timezone.utc)

    event = compose_market_event(
        make_item(published_at=occurred_at),
        EventType.SUPPLY_CONTRACT,
        decision(),
    )

    assert event.occurred_at == occurred_at


def test_compose_market_event_requires_symbol_for_multi_symbol_item() -> None:
    item = make_item(symbols=("005930", "000660"))

    with pytest.raises(MarketEventCompositionError, match="explicit"):
        compose_market_event(item, EventType.OTHER, decision())


def test_compose_market_event_accepts_explicit_symbol_from_item() -> None:
    item = make_item(symbols=("005930", "000660"))

    event = compose_market_event(
        item,
        EventType.OTHER,
        decision(),
        symbol="000660",
    )

    assert event.event_id == "opendart:20260928000123:000660"
    assert event.symbol == "000660"


def test_compose_market_event_rejects_symbol_not_on_item() -> None:
    with pytest.raises(MarketEventCompositionError, match="belong"):
        compose_market_event(
            make_item(),
            EventType.OTHER,
            decision(),
            symbol="000660",
        )


def test_event_id_is_deterministic_for_retries() -> None:
    item = make_item()
    first = compose_market_event(item, EventType.SUPPLY_CONTRACT, decision())
    second = compose_market_event(item, EventType.SUPPLY_CONTRACT, decision())

    assert first.event_id == second.event_id
