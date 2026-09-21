from typing import Protocol

from market_event_analyzer.contract import MarketEvent
from market_event_analyzer.news import RawNewsItem


class NewsCollector(Protocol):
    def collect(self) -> tuple[RawNewsItem, ...]: ...


class EventClassifier(Protocol):
    def classify(self, item: RawNewsItem) -> MarketEvent | None: ...
