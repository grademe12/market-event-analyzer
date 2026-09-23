#!/usr/bin/env python3
import argparse
from time import perf_counter
import json
import os
from pathlib import Path

from market_event_analyzer.classification import ClassificationInput, EventType
from market_event_analyzer.kiro_model import KiroAssessmentError, KiroAssessmentModel


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run enriched DART cases through the central Kiro assessment model."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=Path("eval/kiro_classification_results.jsonl"))
    parser.add_argument("--limit", type=int, default=0, help="Maximum cases to classify; 0 means all.")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when any case fails.")
    args = parser.parse_args()

    if args.limit < 0:
        parser.error("--limit must be zero or positive")
    if not os.getenv("KIRO_API_KEY", "").strip():
        parser.error("KIRO_API_KEY is not set")

    project_root = Path(__file__).resolve().parents[1]
    model = KiroAssessmentModel(timeout_seconds=args.timeout_seconds, working_directory=project_root)
    rows = _load_rows(args.input)
    if args.limit:
        rows = rows[: args.limit]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    failures = 0
    with args.output.open("w", encoding="utf-8") as handle:
        total = len(rows)
        for index, row in enumerate(rows, start=1):
            case_id = str(row.get("case_id", row.get("source_item_id", index)))
            source_item_id = str(row.get("source_item_id", ""))
            started = perf_counter()
            try:
                decision = model.assess(_classification_input(row))
            except (KiroAssessmentError, ValueError, KeyError) as exc:
                failures += 1
                result = {
                    "case_id": case_id,
                    "source_item_id": source_item_id,
                    "symbol": str(row.get("symbol", "")),
                    "model": "deepseek-3.2",
                    "error": str(exc),
                    "latency_ms": round((perf_counter() - started) * 1000),
                }
                print(f"[{index}/{total}] {case_id} FAILED: {exc}", flush=True)
            else:
                result = {
                    "case_id": case_id,
                    "source_item_id": source_item_id,
                    "symbol": str(row["symbol"]),
                    "event_type": str(row["event_type"]),
                    "model": "deepseek-3.2",
                    "decision": decision.to_payload(),
                    "latency_ms": round((perf_counter() - started) * 1000),
                }
                print(
                    f"[{index}/{total}] {case_id} {decision.direction.value}/{decision.impact.value} "
                    f"confidence={decision.confidence:.2f}",
                    flush=True,
                )

            json.dump(result, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\\n")
            handle.flush()

    print(
        f"completed {len(rows)} case(s): {len(rows) - failures} succeeded, "
        f"{failures} failed; results={args.output}",
        flush=True,
    )
    return 1 if args.strict and failures else 0


def _load_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at line {line_number}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"line {line_number} must be a JSON object")
            rows.append(value)
    return rows


def _classification_input(row: dict[str, object]) -> ClassificationInput:
    return ClassificationInput(
        symbol=str(row["symbol"]),
        event_type=EventType(str(row["event_type"])),
        headline=str(row["headline"]),
        body=str(row["body"]),
        source=str(row.get("provider", "opendart")),
        source_item_id=str(row["source_item_id"]),
        provider_event_name=str(row.get("provider_event_name", "")),
    )


if __name__ == "__main__":
    raise SystemExit(main())
