from pathlib import Path

from market_event_analyzer.classification import EventType
from market_event_analyzer.contract import Direction, Impact
from market_event_analyzer.evaluation import load_evaluation_cases


def test_classifier_evaluation_fixture_loads() -> None:
    cases = load_evaluation_cases(Path("eval/classifier_cases.jsonl"))

    assert len(cases) == 6
    assert cases[0].event_type is EventType.SUPPLY_CONTRACT
    assert cases[0].acceptable_directions == (Direction.BUY,)
    assert cases[0].expected_impact is Impact.HIGH
