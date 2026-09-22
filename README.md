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

Synthetic evaluation cases live in `eval/classifier_cases.jsonl`. They are test scenarios for comparing structured-output reliability, direction/impact agreement, latency, and cost; they are not investment labels for real companies.

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

The next milestone is OpenDART disclosure content enrichment, followed by a realistic evaluation corpus and model benchmarking. The implementation sequence, retry semantics, stock-market delivery boundary, and after-hours event policy are defined in [docs/EVENT_ANALYSIS_PIPELINE_PLAN.md](docs/EVENT_ANALYSIS_PIPELINE_PLAN.md).
