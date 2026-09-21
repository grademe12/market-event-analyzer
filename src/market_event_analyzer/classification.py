from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from market_event_analyzer.contract import Direction, Impact


class EventType(StrEnum):
    SUPPLY_CONTRACT = "supply_contract"
    CAPITAL_INCREASE = "capital_increase"
    SHARE_BUYBACK = "share_buyback"
    DIVIDEND = "dividend"
    EARNINGS = "earnings"
    MERGER_ACQUISITION = "merger_acquisition"
    LAWSUIT = "lawsuit"
    DEBT_FINANCING = "debt_financing"
    INVESTMENT_DECISION = "investment_decision"
    MANAGEMENT_CHANGE = "management_change"
    OWNERSHIP_CHANGE = "ownership_change"
    FINANCIAL_DISTRESS = "financial_distress"
    SECURITIES_FILING = "securities_filing"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ClassificationInput:
    symbol: str
    event_type: EventType
    headline: str
    body: str
    source: str
    source_item_id: str
    provider_event_name: str = ""

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be blank")
        if not isinstance(self.event_type, EventType):
            raise ValueError("event_type must be an EventType")
        if not self.headline.strip():
            raise ValueError("headline must not be blank")
        if not self.source.strip():
            raise ValueError("source must not be blank")
        if not self.source_item_id.strip():
            raise ValueError("source_item_id must not be blank")


@dataclass(frozen=True, slots=True)
class ClassificationDecision:
    direction: Direction
    impact: Impact
    confidence: float

    def __post_init__(self) -> None:
        if not isinstance(self.direction, Direction):
            raise ValueError("direction must be a Direction")
        if not isinstance(self.impact, Impact):
            raise ValueError("impact must be an Impact")
        if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
            raise ValueError("confidence must be numeric")
        if not isfinite(float(self.confidence)) or not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")

    def to_payload(self) -> dict[str, object]:
        return {
            "direction": self.direction.value,
            "impact": self.impact.value,
            "confidence": float(self.confidence),
        }
