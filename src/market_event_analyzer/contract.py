from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite


class Direction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    MIXED = "MIXED"


class Impact(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class MarketEvent:
    event_id: str
    symbol: str
    event_type: str
    direction: Direction
    confidence: float
    impact: Impact
    occurred_at: datetime
    detected_at: datetime
    source: str
    source_item_id: str = ""
    headline: str = ""

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id must not be blank")
        if not self.symbol.strip():
            raise ValueError("symbol must not be blank")
        if not self.event_type.strip():
            raise ValueError("event_type must not be blank")
        if not self.source.strip():
            raise ValueError("source must not be blank")
        if not isinstance(self.direction, Direction):
            raise ValueError("direction must be a Direction")
        if not isinstance(self.impact, Impact):
            raise ValueError("impact must be an Impact")
        if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
            raise ValueError("confidence must be numeric")
        if not isfinite(float(self.confidence)) or not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.occurred_at.tzinfo is None or self.detected_at.tzinfo is None:
            raise ValueError("event timestamps must be timezone-aware")
        if self.detected_at < self.occurred_at:
            raise ValueError("detected_at must not be before occurred_at")

    def to_payload(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "symbol": self.symbol,
            "event_type": self.event_type,
            "direction": self.direction.value,
            "confidence": float(self.confidence),
            "impact": self.impact.value,
            "occurred_at": self.occurred_at.isoformat(),
            "detected_at": self.detected_at.isoformat(),
            "source": self.source,
            "source_item_id": self.source_item_id,
            "headline": self.headline,
        }
