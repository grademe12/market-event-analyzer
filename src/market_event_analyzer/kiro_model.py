from collections.abc import Callable
import json
from pathlib import Path
import subprocess
from typing import Any

from market_event_analyzer.classification import (
    ClassificationDecision,
    ClassificationInput,
)
from market_event_analyzer.contract import Direction, Impact


DEFAULT_AGENT_NAME = "market-event-classifier"
DEFAULT_TIMEOUT_SECONDS = 60.0

ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


class KiroAssessmentError(RuntimeError):
    pass


class KiroAssessmentModel:
    """EventAssessmentModel backed by one headless Kiro CLI invocation per event."""

    def __init__(
        self,
        *,
        cli_path: str = "kiro-cli",
        agent_name: str = DEFAULT_AGENT_NAME,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        working_directory: str | Path | None = None,
        run_process: ProcessRunner = subprocess.run,
    ) -> None:
        if not cli_path.strip():
            raise ValueError("cli_path must not be blank")
        if not agent_name.strip():
            raise ValueError("agent_name must not be blank")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._cli_path = cli_path
        self._agent_name = agent_name
        self._timeout_seconds = timeout_seconds
        self._working_directory = (
            str(Path(working_directory))
            if working_directory is not None
            else None
        )
        self._run_process = run_process

    def assess(self, item: ClassificationInput) -> ClassificationDecision:
        prompt = _build_prompt(item)
        command = [
            self._cli_path,
            "chat",
            "--agent",
            self._agent_name,
            "--no-interactive",
        ]

        try:
            result = self._run_process(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=self._timeout_seconds,
                check=False,
                cwd=self._working_directory,
            )
        except FileNotFoundError as exc:
            raise KiroAssessmentError(
                f"Kiro CLI executable not found: {self._cli_path}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise KiroAssessmentError(
                f"Kiro CLI timed out after {self._timeout_seconds:g}s"
            ) from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            if len(detail) > 500:
                detail = detail[:500] + "..."
            suffix = f": {detail}" if detail else ""
            raise KiroAssessmentError(
                f"Kiro CLI exited with status {result.returncode}{suffix}"
            )

        return _parse_decision(result.stdout)


def _build_prompt(item: ClassificationInput) -> str:
    return (
        "Classify this disclosure for simulated participant reaction.\n"
        f"symbol: {item.symbol}\n"
        f"event_type: {item.event_type.value}\n"
        f"source: {item.source}\n"
        f"source_item_id: {item.source_item_id}\n"
        f"provider_event_name: {item.provider_event_name}\n"
        f"headline: {item.headline}\n"
        "body:\n"
        f"{item.body}\n"
    )


def _parse_decision(output: str) -> ClassificationDecision:
    payload = _extract_json_object(output)
    try:
        direction = Direction(str(payload["direction"]).upper())
        impact = Impact(str(payload["impact"]).lower())
        confidence = float(payload["confidence"])
        return ClassificationDecision(
            direction=direction,
            impact=impact,
            confidence=confidence,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise KiroAssessmentError(
            "Kiro response does not match ClassificationDecision"
        ) from exc


def _extract_json_object(output: str) -> dict[str, Any]:
    text = output.strip()
    if not text:
        raise KiroAssessmentError("Kiro returned an empty response")

    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value

    raise KiroAssessmentError("Kiro response does not contain a JSON object")
