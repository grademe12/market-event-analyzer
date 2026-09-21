import pytest

from market_event_analyzer.classification import (
    ClassificationDecision,
    ClassificationInput,
    EventType,
)
from market_event_analyzer.contract import Direction, Impact


def test_classification_decision_serializes_to_stable_payload() -> None:
    decision = ClassificationDecision(
        direction=Direction.BUY,
        impact=Impact.HIGH,
        confidence=0.84,
    )

    assert decision.to_payload() == {
        "direction": "BUY",
        "impact": "high",
        "confidence": 0.84,
    }


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("inf"), float("nan")])
def test_classification_decision_rejects_invalid_confidence(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        ClassificationDecision(
            direction=Direction.MIXED,
            impact=Impact.MEDIUM,
            confidence=confidence,
        )


def test_classification_input_requires_source_identity() -> None:
    with pytest.raises(ValueError, match="source_item_id"):
        ClassificationInput(
            symbol="005930",
            event_type=EventType.SUPPLY_CONTRACT,
            headline="Example",
            body="",
            source="opendart",
            source_item_id="",
        )
