from typing import Protocol

from market_event_analyzer.classification import (
    ClassificationDecision,
    ClassificationInput,
)
from market_event_analyzer.contract import MarketEvent
from market_event_analyzer.news import RawNewsItem


class NewsCollector(Protocol):
    def collect(self) -> tuple[RawNewsItem, ...]: ...


class DisclosureEnricher(Protocol):
    def enrich(self, item: RawNewsItem) -> RawNewsItem: ...


class EventClassifier(Protocol):
    def classify(self, item: RawNewsItem) -> MarketEvent | None: ...


class EventAssessmentModel(Protocol):
    def assess(self, item: ClassificationInput) -> ClassificationDecision: ...
