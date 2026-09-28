from market_event_analyzer.classification import (
    ClassificationDecision,
    EventType,
)
from market_event_analyzer.contract import MarketEvent
from market_event_analyzer.news import RawNewsItem


class MarketEventCompositionError(ValueError):
    pass


def compose_market_event(
    item: RawNewsItem,
    event_type: EventType,
    decision: ClassificationDecision,
    *,
    symbol: str | None = None,
) -> MarketEvent:
    """Compose one normalized MarketEvent without inventing provider timestamps."""
    resolved_symbol = _resolve_symbol(item, symbol)
    return MarketEvent(
        event_id=_event_id(item, resolved_symbol),
        symbol=resolved_symbol,
        event_type=event_type.value,
        direction=decision.direction,
        confidence=decision.confidence,
        impact=decision.impact,
        occurred_at=item.published_at,
        detected_at=item.detected_at,
        source=item.provider,
        source_item_id=item.provider_item_id,
        headline=item.headline,
    )


def _resolve_symbol(item: RawNewsItem, symbol: str | None) -> str:
    if symbol is not None:
        normalized = symbol.strip()
        if not normalized:
            raise MarketEventCompositionError("symbol must not be blank")
        if normalized not in item.symbols:
            raise MarketEventCompositionError(
                "symbol must belong to the source item"
            )
        return normalized

    if not item.symbols:
        raise MarketEventCompositionError(
            "source item must contain a symbol"
        )
    if len(item.symbols) != 1:
        raise MarketEventCompositionError(
            "symbol must be explicit when the source item has multiple symbols"
        )
    return item.symbols[0]


def _event_id(item: RawNewsItem, symbol: str) -> str:
    return f"{item.provider}:{item.provider_item_id}:{symbol}"
