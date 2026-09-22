from dataclasses import dataclass
import json
from pathlib import Path

from market_event_analyzer.classification import EventType
from market_event_analyzer.contract import Direction, Impact


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    symbol: str
    event_type: EventType
    headline: str
    body: str
    acceptable_directions: tuple[Direction, ...]
    acceptable_impacts: tuple[Impact, ...]
    provider: str = ""
    source_item_id: str = ""
    source_url: str = ""

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must not be blank")
        if not self.symbol.strip():
            raise ValueError("symbol must not be blank")
        if not self.headline.strip():
            raise ValueError("headline must not be blank")
        if not self.body.strip():
            raise ValueError("body must not be blank")
        if not self.acceptable_directions:
            raise ValueError("acceptable_directions must not be empty")
        if not self.acceptable_impacts:
            raise ValueError("acceptable_impacts must not be empty")

    @property
    def expected_impact(self) -> Impact:
        """Backward-compatible access for single-impact synthetic fixtures."""
        if len(self.acceptable_impacts) != 1:
            raise ValueError("evaluation case has multiple acceptable impacts")
        return self.acceptable_impacts[0]


def load_evaluation_cases(path: str | Path) -> tuple[EvaluationCase, ...]:
    cases: list[EvaluationCase] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                raw_impacts = raw.get("acceptable_impacts")
                if raw_impacts is None:
                    raw_impacts = [raw["expected_impact"]]
                cases.append(
                    EvaluationCase(
                        case_id=str(raw["case_id"]),
                        symbol=str(raw["symbol"]),
                        event_type=EventType(raw["event_type"]),
                        headline=str(raw["headline"]),
                        body=str(raw["body"]),
                        acceptable_directions=tuple(
                            Direction(value)
                            for value in raw["acceptable_directions"]
                        ),
                        acceptable_impacts=tuple(
                            Impact(value)
                            for value in raw_impacts
                        ),
                        provider=str(raw.get("provider", "")),
                        source_item_id=str(raw.get("source_item_id", "")),
                        source_url=str(raw.get("source_url", "")),
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"invalid evaluation case at line {line_number}"
                ) from exc
    return tuple(cases)
