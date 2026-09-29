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

`OpenDartDisclosureEnricher` uses the 14-digit receipt number to download the OpenDART original-document ZIP, selects the main receipt XML, converts DART markup and tables into bounded readable text, and returns a new `RawNewsItem` with `body` populated. The live worker runs this behind durable processing state, so a transient enrichment failure remains retryable instead of being mistaken for successful processing.

Set the API key only through the environment:

```bash
export OPENDART_API_KEY='...'
```

## Durable analysis processing

The live analysis path now persists processing progress in SQLite:

```text
DISCOVERED
   ↓ enrichment + event-type normalization
ENRICHED
   ↓ Kiro assessment + MarketEvent composition
CLASSIFIED
   ↓ idempotent HTTP delivery
DELIVERED
```

`SQLiteProcessingStore` stores the original/enriched item, normalized event type, retry count, last error, and the classified `MarketEvent`. A transient enrichment failure stays at `DISCOVERED`; a transient model failure stays at `ENRICHED`. Pending rows are retried even when a later provider poll no longer returns that disclosure, and a `CLASSIFIED` row is not sent through Kiro again.

`DurableAnalysisPipeline` composes the existing provider-neutral boundaries:

```text
NewsCollector
→ SQLite DISCOVERED
→ DisclosureEnricher
→ EventTypeNormalizer
→ SQLite ENRICHED
→ EventAssessmentModel
→ compose_market_event()
→ SQLite CLASSIFIED
```

After classification, `DurableDeliveryWorker` reads the persisted `MarketEvent` and posts it to the stock-market ingest endpoint. Any 2xx response is treated as successful delivery, including the consumer's idempotent duplicate response. Network/HTTP failures leave the row at `CLASSIFIED` with the error recorded, so the next delivery attempt reuses the stored event without repeating enrichment or Kiro inference.

Run one delivery pass with:

```bash
PYTHONPATH=src python scripts/deliver_classified_events.py \
  --database data/processing.sqlite3
```

The endpoint defaults to `http://127.0.0.1:8000/api/v1/events/` and can be changed with `STOCK_MARKET_EVENT_URL` or `--endpoint`.

## Live worker

The production-like entrypoint continuously composes the existing durable analysis and delivery stages:

```text
OpenDART poll
  -> DISCOVERED
  -> document enrichment
  -> ENRICHED
  -> Kiro / DeepSeek 3.2 once
  -> CLASSIFIED
  -> stock-market gateway
  -> DELIVERED
  -> sleep
  -> repeat
```

Provider polling failures are logged and converted to an empty collection cycle so already stored `DISCOVERED`, `ENRICHED`, and `CLASSIFIED` work can still retry. Per-item enrichment/model/delivery failures keep their durable state and are retried on later cycles.

Prepare a local environment file:

```bash
cp .env.example .env
chmod 600 .env
```

At minimum set `OPENDART_API_KEY`, `KIRO_API_KEY`, and the correct `STOCK_MARKET_EVENT_URL`. For a systemd service, set `KIRO_CLI_PATH` to the absolute output of `which kiro-cli` if the service PATH does not contain it.

To avoid spending model calls on unrelated disclosures, `MARKET_EVENT_SYMBOLS` can contain comma-separated six-digit tickers such as:

```text
MARKET_EVENT_SYMBOLS=005930,000660
```

An empty value means all listed-company disclosures are eligible for analysis.

Run one end-to-end cycle before daemonizing:

```bash
set -a
source .env
set +a
python -m market_event_analyzer --once
```

Then start the continuous worker:

```bash
python -m market_event_analyzer
```

The editable install also exposes the equivalent `market-event-analyzer` command.

### systemd user service

The included unit assumes the repository is `~/market-event-analyzer` and reads `.env` from that directory. If the checkout lives elsewhere, edit the unit paths before installing it.

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/market-event-analyzer.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now market-event-analyzer.service
systemctl --user status market-event-analyzer.service
journalctl --user -u market-event-analyzer.service -f
```

To keep the user service running after logout and start it across reboots, enable lingering once:

```bash
sudo loginctl enable-linger "$USER"
```

## Polling and deduplication

The live worker relies on `SQLiteProcessingStore` as the durable identity boundary: `(provider, provider_item_id)` is inserted once, so repeated OpenDART polls do not cause repeated enrichment or model calls. The older `SQLiteSeenItemStore` / `DeduplicatingCollector` utilities remain available for standalone polling use cases, but they are not the live analysis path.

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
  "occurred_at": null,
  "detected_at": "2026-09-21T08:20:12+09:00",
  "source": "provider-name",
  "source_item_id": "provider-123",
  "headline": "Example supply contract announcement"
}
```

The contract intentionally does not contain trader activation ratios, order quantities, or BUY/SELL probabilities. Those are workload-simulation concerns owned by the consumer.

`occurred_at` is nullable. Providers such as the OpenDART list API may not expose an exact event timestamp, so the analyzer keeps the exact `detected_at` while representing the unknown occurrence time as `null` instead of fabricating it. `compose_market_event()` combines an enriched `RawNewsItem`, normalized `EventType`, and one `ClassificationDecision` into a deterministic event ID of the form `provider:source_item_id:symbol`.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

With stock-market session-aware runner dispatch in place, the live worker completes the continuous OpenDART → Kiro → MarketEvent → stock-market path. Operational follow-up can focus on metrics, alerting, and expanding provider coverage rather than adding runner-side model calls.
