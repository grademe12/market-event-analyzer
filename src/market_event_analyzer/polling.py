from collections.abc import Callable
from dataclasses import dataclass
import time

from market_event_analyzer.interfaces import NewsCollector
from market_event_analyzer.news import RawNewsItem


Sleep = Callable[[float], None]
ItemHandler = Callable[[tuple[RawNewsItem, ...]], None]


@dataclass(frozen=True, slots=True)
class PollCycle:
    cycle: int
    items: tuple[RawNewsItem, ...]


class CollectorPoller:
    def __init__(
        self,
        collector: NewsCollector,
        *,
        interval_seconds: float = 30.0,
        sleep: Sleep = time.sleep,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._collector = collector
        self._interval_seconds = interval_seconds
        self._sleep = sleep

    def run_once(self, *, cycle: int = 1) -> PollCycle:
        if cycle < 1:
            raise ValueError("cycle must be positive")
        return PollCycle(cycle=cycle, items=self._collector.collect())

    def run(
        self,
        handler: ItemHandler,
        *,
        max_cycles: int | None = None,
    ) -> None:
        if max_cycles is not None and max_cycles < 1:
            raise ValueError("max_cycles must be positive when provided")

        cycle = 1
        while max_cycles is None or cycle <= max_cycles:
            result = self.run_once(cycle=cycle)
            handler(result.items)
            if max_cycles is not None and cycle >= max_cycles:
                return
            self._sleep(self._interval_seconds)
            cycle += 1
