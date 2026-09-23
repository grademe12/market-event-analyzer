import subprocess

import pytest

from market_event_analyzer.classification import ClassificationInput, EventType
from market_event_analyzer.contract import Direction, Impact
from market_event_analyzer.kiro_model import KiroAssessmentError, KiroAssessmentModel


def classification_input() -> ClassificationInput:
    return ClassificationInput(
        symbol="005930",
        event_type=EventType.SUPPLY_CONTRACT,
        headline="테스트회사: 단일판매ㆍ공급계약체결",
        body="계약금액은 최근 매출액 대비 18.4% 규모다.",
        source="opendart",
        source_item_id="20260923000123",
        provider_event_name="단일판매ㆍ공급계약체결",
    )


def test_assess_uses_stdin_and_returns_domain_decision() -> None:
    captured = {}

    def run_process(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command, 0,
            stdout='{"direction":"BUY","impact":"high","confidence":0.87}\\n',
            stderr="",
        )

    decision = KiroAssessmentModel(
        run_process=run_process,
        working_directory="/repo",
    ).assess(classification_input())

    assert decision.direction is Direction.BUY
    assert decision.impact is Impact.HIGH
    assert decision.confidence == pytest.approx(0.87)
    assert captured["command"] == [
        "kiro-cli", "chat", "--agent", "market-event-classifier", "--no-interactive"
    ]
    assert "계약금액은 최근 매출액 대비 18.4%" in captured["kwargs"]["input"]
    assert captured["kwargs"]["cwd"] == "/repo"
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["check"] is False


def test_markdown_wrapped_json_is_tolerated() -> None:
    def run_process(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 0,
            stdout='```json\\n{"direction":"MIXED","impact":"medium","confidence":0.61}\\n```\\n',
            stderr="",
        )

    decision = KiroAssessmentModel(run_process=run_process).assess(classification_input())

    assert decision.direction is Direction.MIXED
    assert decision.impact is Impact.MEDIUM


def test_invalid_decision_is_rejected() -> None:
    def run_process(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 0,
            stdout='{"direction":"HOLD","impact":"high","confidence":0.9}',
            stderr="",
        )

    with pytest.raises(KiroAssessmentError, match="ClassificationDecision"):
        KiroAssessmentModel(run_process=run_process).assess(classification_input())


def test_nonzero_cli_exit_is_reported_without_prompt_contents() -> None:
    def run_process(command, **kwargs):
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="authentication failed")

    with pytest.raises(KiroAssessmentError, match="status 2") as exc_info:
        KiroAssessmentModel(run_process=run_process).assess(classification_input())

    assert "계약금액" not in str(exc_info.value)


def test_cli_timeout_is_translated() -> None:
    def run_process(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"])

    with pytest.raises(KiroAssessmentError, match="timed out"):
        KiroAssessmentModel(run_process=run_process, timeout_seconds=12).assess(
            classification_input()
        )


def test_empty_response_is_rejected() -> None:
    def run_process(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="   ", stderr="")

    with pytest.raises(KiroAssessmentError, match="empty response"):
        KiroAssessmentModel(run_process=run_process).assess(classification_input())
