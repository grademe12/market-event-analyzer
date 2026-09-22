#!/usr/bin/env python3
import argparse
from collections import Counter
from datetime import date
import os
from pathlib import Path

from market_event_analyzer.corpus import (
    build_dart_corpus_candidates,
    write_draft_cases,
)
from market_event_analyzer.providers.opendart import OpenDartCollector
from market_event_analyzer.providers.opendart_document import (
    OpenDartDisclosureEnricher,
)


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a reviewable evaluation-corpus draft from real OpenDART filings."
    )
    parser.add_argument("--start-date", required=True, type=parse_date)
    parser.add_argument("--end-date", required=True, type=parse_date)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("eval/dart_classifier_candidates.jsonl"),
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--max-per-event-type", type=int, default=5)
    parser.add_argument("--exclude-other", action="store_true")
    parser.add_argument("--max-body-chars", type=int, default=12_000)
    args = parser.parse_args()

    api_key = os.getenv("OPENDART_API_KEY", "").strip()
    if not api_key:
        parser.error("OPENDART_API_KEY is not set")

    collector = OpenDartCollector(api_key)
    enricher = OpenDartDisclosureEnricher(
        api_key,
        max_body_chars=args.max_body_chars,
    )
    result = build_dart_corpus_candidates(
        collector,
        enricher,
        start_date=args.start_date,
        end_date=args.end_date,
        limit=args.limit,
        max_per_event_type=args.max_per_event_type,
        include_other=not args.exclude_other,
    )
    write_draft_cases(args.output, result.cases)

    counts = Counter(case.event_type.value for case in result.cases)
    print(f"wrote {len(result.cases)} case(s) to {args.output}")
    print(f"attempted enrichment: {result.attempted_enrichments}")
    print(f"enrichment failures: {len(result.failed_enrichments)}")
    for event_type, count in sorted(counts.items()):
        print(f"  {event_type}: {count}")
    if result.failed_enrichments:
        print("failed receipt numbers:")
        for receipt_no in result.failed_enrichments:
            print(f"  {receipt_no}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
