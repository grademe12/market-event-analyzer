import json
import subprocess

import pytest

from market_event_analyzer.claude_model import (
    DECISION_SCHEMA,
    SYSTEM_PROMPT,
    ClaudeAssessmentError,
    ClaudeAssessmentModel,
)
from market_event_analyzer.classification import ClassificationInput, EventType
from market_event_analyzer.contract import Direction, Impact
from market_event_analyzer.live import LiveConfig, build_assessment_model
from market_event_analyzer.kiro_model import KiroAssessmentModel


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


def envelope(**fields) -> str:
    base = {"type": "result", "subtype": "success", "is_error": False, "result": ""}
    base.update(fields)
    return json.dumps(base)


def test_assess_reads_structured_output_and_sends_prompt_on_stdin() -> None:
    captured = {}

    def run_process(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=envelope(
                structured_output={"direction": "BUY", "impact": "high", "confidence": 0.87},
                total_cost_usd=0.006,
            ),
            stderr="",
        )

    decision = ClaudeAssessmentModel(run_process=run_process, working_directory="/repo").assess(
        classification_input()
    )

    assert decision.direction is Direction.BUY
    assert decision.impact is Impact.HIGH
    assert decision.confidence == pytest.approx(0.87)
    command = captured["command"]
    assert command[:4] == ["claude", "-p", "--model", "sonnet"]
    # No tools, no MCP, no settings, no saved session.
    assert command[command.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in command
    assert command[command.index("--setting-sources") + 1] == ""
    assert "--no-session-persistence" in command
    assert command[command.index("--system-prompt") + 1] == SYSTEM_PROMPT
    assert command[command.index("--json-schema") + 1] == DECISION_SCHEMA
    assert "계약금액은 최근 매출액 대비 18.4%" in captured["kwargs"]["input"]
    assert captured["kwargs"]["cwd"] == "/repo"
    assert captured["kwargs"]["check"] is False


def test_result_text_is_used_when_structured_output_is_missing() -> None:
    def run_process(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=envelope(result='{"direction":"mixed","impact":"MEDIUM","confidence":0.6}'),
            stderr="",
        )

    decision = ClaudeAssessmentModel(run_process=run_process).assess(classification_input())

    assert decision.direction is Direction.MIXED
    assert decision.impact is Impact.MEDIUM


def test_error_envelope_raises_with_detail() -> None:
    def run_process(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 1, stdout=envelope(is_error=True, result="Not logged in"), stderr=""
        )

    with pytest.raises(ClaudeAssessmentError, match="status 1: Not logged in"):
        ClaudeAssessmentModel(run_process=run_process).assess(classification_input())


def test_invalid_decision_raises() -> None:
    def run_process(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=envelope(structured_output={"direction": "UP", "impact": "high", "confidence": 1}),
            stderr="",
        )

    with pytest.raises(ClaudeAssessmentError, match="does not match"):
        ClaudeAssessmentModel(run_process=run_process).assess(classification_input())


def test_timeout_and_missing_cli_are_assessment_errors() -> None:
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 60)

    def missing(command, **kwargs):
        raise FileNotFoundError(command[0])

    with pytest.raises(ClaudeAssessmentError, match="timed out"):
        ClaudeAssessmentModel(run_process=timeout).assess(classification_input())
    with pytest.raises(ClaudeAssessmentError, match="not found"):
        ClaudeAssessmentModel(run_process=missing).assess(classification_input())


def test_live_config_defaults_to_claude_without_kiro_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENDART_API_KEY", "dart-key")
    monkeypatch.delenv("KIRO_API_KEY", raising=False)
    monkeypatch.delenv("MARKET_EVENT_ASSESSOR", raising=False)
    monkeypatch.setenv("CLAUDE_CLI_PATH", "/home/u/.local/bin/claude")
    monkeypatch.setenv("MARKET_EVENT_WORKDIR", str(tmp_path))

    config = LiveConfig.from_environment()

    assert config.assessor == "claude"
    assert config.claude_model == "sonnet"
    assert isinstance(build_assessment_model(config), ClaudeAssessmentModel)


def test_live_config_kiro_backend_still_requires_its_key(monkeypatch) -> None:
    monkeypatch.setenv("OPENDART_API_KEY", "dart-key")
    monkeypatch.setenv("MARKET_EVENT_ASSESSOR", "kiro")
    monkeypatch.delenv("KIRO_API_KEY", raising=False)

    with pytest.raises(ValueError, match="KIRO_API_KEY"):
        LiveConfig.from_environment()

    monkeypatch.setenv("KIRO_API_KEY", "kiro-key")
    assert isinstance(build_assessment_model(LiveConfig.from_environment()), KiroAssessmentModel)


def test_unknown_assessor_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("OPENDART_API_KEY", "dart-key")
    monkeypatch.setenv("MARKET_EVENT_ASSESSOR", "gpt")

    with pytest.raises(ValueError, match="MARKET_EVENT_ASSESSOR"):
        LiveConfig.from_environment()
