from dataclasses import dataclass

from market_event_analyzer.contract import MarketEvent
from market_event_analyzer.interfaces import EventClassifier, NewsCollector


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    collected_count: int
    classified_count: int
    ignored_count: int
    events: tuple[MarketEvent, ...]


class AnalysisPipeline:
    def __init__(
        self,
        collector: NewsCollector,
        classifier: EventClassifier,
    ) -> None:
        self._collector = collector
        self._classifier = classifier

    def run_once(self) -> AnalysisResult:
        items = self._collector.collect()
        events: list[MarketEvent] = []

        for item in items:
            event = self._classifier.classify(item)
            if event is not None:
                events.append(event)

        return AnalysisResult(
            collected_count=len(items),
            classified_count=len(events),
            ignored_count=len(items) - len(events),
            events=tuple(events),
        )
