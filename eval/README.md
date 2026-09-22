# Classifier evaluation fixtures

The repository keeps two kinds of classifier evaluation data.

## Synthetic regression cases

`classifier_cases.jsonl` contains small synthetic scenarios for schema/regression checks. They are not investment labels or claims about real companies.

## Real OpenDART corpus

Real filing cases are built in two steps so source text and human labels stay auditable.

First, generate a review draft from live OpenDART data:

```bash
export OPENDART_API_KEY='...'
PYTHONPATH=src python scripts/build_dart_eval_corpus.py \
  --start-date 2026-09-01 \
  --end-date 2026-09-22 \
  --limit 50 \
  --max-per-event-type 5 \
  --output eval/dart_classifier_candidates.jsonl
```

The generator:

- reads actual listed-company disclosures from the requested date range,
- uses `DartEventTypeNormalizer` before document download,
- limits each event type before enrichment to avoid unnecessary document API calls,
- downloads and cleans the selected original DART documents,
- preserves `provider`, `source_item_id`, and `source_url`,
- writes `review_status: "pending"` with empty human-label fields.

The generated draft is **not** a benchmark until it has been reviewed. For each retained case, fill:

```json
{
  "acceptable_directions": ["BUY", "MIXED"],
  "acceptable_impacts": ["medium", "high"],
  "review_status": "reviewed"
}
```

Use a single value when the interpretation is clear. Multiple acceptable values are preferred when a disclosure is genuinely ambiguous. Do not force a strong directional label merely to make scoring easier.

After review, move/copy the approved rows into `eval/dart_classifier_cases.jsonl`. The standard `load_evaluation_cases()` loader accepts provider provenance and multiple acceptable impacts, while remaining compatible with the older synthetic `expected_impact` field.

Do not commit an API key. Public filing text may be committed for reproducible evaluation, but keep the corpus intentionally small and focused on the model inputs needed by this project.

## Benchmark metrics

The first model comparison should score at least:

- structured output validity,
- direction agreement with `acceptable_directions`,
- impact agreement with `acceptable_impacts`,
- invalid/empty response rate,
- latency,
- token usage when available,
- estimated cost per analyzed item.

Confidence is intentionally not given a fixed target because it is model-calibration dependent.
