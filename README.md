# market-event-analyzer

Financial news and disclosure events normalized into a small market-event contract.

This project is intentionally separate from `stock-market`.

- **market-event-analyzer** collects and analyzes external news/disclosures.
- **stock-market** consumes normalized events and decides how simulated traders react.
- This project does **not** place real brokerage orders.

## Boundaries

The analyzer owns the meaning of an external event: what symbol it belongs to, whether the event is interpreted as BUY/SELL/MIXED, how confident that interpretation is, and how large the impact appears to be.

The consumer owns reaction policy. For example, `stock-market` may convert a high-impact BUY event into a larger dormant-trader activation ratio. That policy does not belong here.

The analysis path is intentionally split into replaceable boundaries:

```text
external provider
      |
      v
NewsCollector
      |
      v
RawNewsItem
      |
      v
event-type normalizer
      |
      v
ClassificationInput
      |
      v
EventAssessmentModel
      |
      v
ClassificationDecision
      |
      v
MarketEvent
```

The model boundary is intentionally provider-neutral. OpenAI, Gemini, Claude, a local model, or a rule-based implementation can satisfy the same `EventAssessmentModel` contract.

## OpenDART collector

`OpenDartCollector` queries the OpenDART disclosure list for the current Korea date, follows all result pages, and emits listed-company disclosures as `RawNewsItem` values.

OpenDART provides the filing date but not an exact filing timestamp in the list response. The collector therefore leaves `published_at` unknown and records the exact time this process first observed the disclosure in `detected_at`.

The provider-supplied six-digit stock code is preserved in `RawNewsItem.symbols`, and the original DART `report_nm` is preserved in `provider_event_name`. Classification code does not need to parse it back out of a display headline.

`OpenDartDisclosureEnricher` uses the 14-digit receipt number to download the OpenDART original-document ZIP, selects the main receipt XML, converts DART markup and tables into bounded readable text, and returns a new `RawNewsItem` with `body` populated. It intentionally remains separate from polling/dedup until durable processing state is added, so a transient enrichment failure cannot be mistaken for successful processing.

Set the API key only through the environment:

```bash
export OPENDART_API_KEY='...'
```

## Polling and deduplication

Repeated provider polling is composed from two small pieces:

```text
OpenDartCollector
      |
      v
DeduplicatingCollector
      |
      v
CollectorPoller
      |
      v
new RawNewsItem values only
```

`SQLiteSeenItemStore` uses `(provider, provider_item_id)` as the durable identity, so an OpenDART `rcept_no` is emitted once even if the process restarts and the provider returns the same disclosure again.

## Classification contract

`DartEventTypeNormalizer` maps structured DART report names into a stable, small `EventType` vocabulary before any model call. Unknown filings deliberately fall back to `other`.

The model receives `ClassificationInput` and must return only a `ClassificationDecision`:

```json
{
  "direction": "BUY",
  "impact": "high",
  "confidence": 0.84
}
```

That keeps provider SDKs and model response formats outside the core domain contract.

Synthetic evaluation cases live in `eval/classifier_cases.jsonl`. Real OpenDART samples can be generated with `scripts/build_dart_eval_corpus.py` and used as realistic smoke inputs for the model adapter. The project does not require a gold-label investment benchmark; the purpose is to turn each real disclosure into one plausible reaction decision that can later drive simulated participant spikes.

## Kiro assessment model

`KiroAssessmentModel` implements the existing `EventAssessmentModel` boundary with one headless Kiro CLI invocation per disclosure. The workspace agent `.kiro/agents/market-event-classifier.json` pins `deepseek-3.2`, disables tools/MCP/powers, and asks for only:

```json
{
  "direction": "BUY",
  "impact": "high",
  "confidence": 0.87
}
```

The disclosure text is sent through stdin rather than command-line arguments.

Prerequisites:

```bash
# Install/sign in to a current Kiro CLI, then create an API key at app.kiro.dev.
export KIRO_API_KEY='ksk_...'
```

Run a downloaded DART corpus artifact through the central classifier:

```bash
PYTHONPATH=src python scripts/run_kiro_classification_smoke.py \
  /path/to/dart_classifier_candidates.jsonl \
  --output eval/kiro_classification_results.jsonl
```

The smoke runner checks that `deepseek-3.2` is available, classifies each disclosure once, prints concise progress, and writes decision/latency rows to JSONL. It does not fan out model calls to participant runners.

## MarketEvent

Example payload:

```json
{
  "event_id": "news-20260921-0001",
  "symbol": "005930",
  "event_type": "supply_contract",
  "direction": "BUY",
  "confidence": 0.84,
  "impact": "high",
  "occurred_at": "2026-09-21T08:20:00+09:00",
  "detected_at": "2026-09-21T08:20:12+09:00",
  "source": "provider-name",
  "source_item_id": "provider-123",
  "headline": "Example supply contract announcement"
}
```

The contract intentionally does not contain trader activation ratios, order quantities, or BUY/SELL probabilities. Those are workload-simulation concerns owned by the consumer.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

The next milestone after the Kiro smoke run is composing the resulting `ClassificationDecision` into one `MarketEvent` per disclosure, then delivering that event to `stock-market` for runner-side reaction fan-out. The implementation sequence, retry semantics, stock-market delivery boundary, and after-hours event policy are defined in [docs/EVENT_ANALYSIS_PIPELINE_PLAN.md](docs/EVENT_ANALYSIS_PIPELINE_PLAN.md).
