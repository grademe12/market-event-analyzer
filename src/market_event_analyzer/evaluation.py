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
    expected_impact: Impact


def load_evaluation_cases(path: str | Path) -> tuple[EvaluationCase, ...]:
    cases: list[EvaluationCase] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
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
                        expected_impact=Impact(raw["expected_impact"]),
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"invalid evaluation case at line {line_number}"
                ) from exc
    return tuple(cases)
