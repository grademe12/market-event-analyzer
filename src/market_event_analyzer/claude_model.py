from collections.abc import Callable
import json
import logging
from pathlib import Path
import subprocess
from typing import Any

from market_event_analyzer.classification import (
    ClassificationDecision,
    ClassificationInput,
)
from market_event_analyzer.contract import Direction, Impact
from market_event_analyzer.kiro_model import _build_prompt


DEFAULT_MODEL = "sonnet"
DEFAULT_TIMEOUT_SECONDS = 60.0

# Same instructions as .kiro/agents/market-event-classifier.json, so the two
# backends answer the same question.
SYSTEM_PROMPT = (
    "You classify public market disclosures for a simulated workload generator. "
    "For each disclosure, estimate a plausible immediate market reaction. "
    "Return only one JSON object with exactly these fields: direction (BUY, SELL, or MIXED), "
    "impact (low, medium, or high), and confidence (number from 0.0 to 1.0). "
    "Use MIXED when positive and negative implications conflict or direction is genuinely ambiguous. "
    "Impact represents how strongly simulated participants should react, not a price forecast. "
    "Do not give investment advice, explanations, markdown, or any text outside the JSON object."
)

DECISION_SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {
            "direction": {"enum": ["BUY", "SELL", "MIXED"]},
            "impact": {"enum": ["low", "medium", "high"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["direction", "impact", "confidence"],
        "additionalProperties": False,
    },
    separators=(",", ":"),
)

ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]

logger = logging.getLogger(__name__)


class ClaudeAssessmentError(RuntimeError):
    pass


class ClaudeAssessmentModel:
    """EventAssessmentModel backed by one headless Claude Code CLI call per event.

    Runs ``claude -p`` with no tools, no MCP servers, no settings files and no
    saved session, and asks for structured output that matches
    ``ClassificationDecision``. Uses the CLI's own login, so no API key is
    passed here.
    """

    def __init__(
        self,
        *,
        cli_path: str = "claude",
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        working_directory: str | Path | None = None,
        run_process: ProcessRunner = subprocess.run,
    ) -> None:
        if not cli_path.strip():
            raise ValueError("cli_path must not be blank")
        if not model.strip():
            raise ValueError("model must not be blank")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._cli_path = cli_path
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._working_directory = (
            str(Path(working_directory))
            if working_directory is not None
            else None
        )
        self._run_process = run_process

    def command(self) -> list[str]:
        return [
            self._cli_path,
            "-p",
            "--model",
            self._model,
            "--output-format",
            "json",
            "--tools",
            "",
            "--strict-mcp-config",
            "--setting-sources",
            "",
            "--no-session-persistence",
            "--system-prompt",
            SYSTEM_PROMPT,
            "--json-schema",
            DECISION_SCHEMA,
        ]

    def assess(self, item: ClassificationInput) -> ClassificationDecision:
        command = self.command()
        try:
            result = self._run_process(
                command,
                input=_build_prompt(item),
                text=True,
                capture_output=True,
                timeout=self._timeout_seconds,
                check=False,
                cwd=self._working_directory,
            )
        except FileNotFoundError as exc:
            raise ClaudeAssessmentError(
                f"Claude CLI executable not found: {self._cli_path}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ClaudeAssessmentError(
                f"Claude CLI timed out after {self._timeout_seconds:g}s"
            ) from exc

        envelope = _parse_envelope(result.stdout)
        if result.returncode != 0 or envelope.get("is_error"):
            detail = str(envelope.get("result") or result.stderr or result.stdout or "").strip()
            if len(detail) > 500:
                detail = detail[:500] + "..."
            suffix = f": {detail}" if detail else ""
            raise ClaudeAssessmentError(
                f"Claude CLI exited with status {result.returncode}{suffix}"
            )

        decision = _parse_decision(envelope)
        logger.info(
            "event=claude_assessment source_item_id=%s model=%s direction=%s impact=%s "
            "confidence=%.2f cost_usd=%s duration_ms=%s",
            item.source_item_id,
            self._model,
            decision.direction.value,
            decision.impact.value,
            decision.confidence,
            envelope.get("total_cost_usd", ""),
            envelope.get("duration_ms", ""),
        )
        return decision


def _parse_envelope(output: str) -> dict[str, Any]:
    text = (output or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _parse_decision(envelope: dict[str, Any]) -> ClassificationDecision:
    payload = envelope.get("structured_output")
    if not isinstance(payload, dict):
        # Older CLIs put the JSON text in "result" only.
        try:
            payload = json.loads(str(envelope.get("result", "")))
        except json.JSONDecodeError as exc:
            raise ClaudeAssessmentError("Claude response does not contain a JSON object") from exc
    if not isinstance(payload, dict):
        raise ClaudeAssessmentError("Claude response does not contain a JSON object")
    try:
        return ClassificationDecision(
            direction=Direction(str(payload["direction"]).upper()),
            impact=Impact(str(payload["impact"]).lower()),
            confidence=float(payload["confidence"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ClaudeAssessmentError(
            "Claude response does not match ClassificationDecision"
        ) from exc
