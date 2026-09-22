# Event Analysis Pipeline Plan

## 1. Purpose

This document defines the implementation path from the current OpenDART metadata collector to a durable event-analysis pipeline that can drive simulated market reactions in `stock-market`.

The target flow is:

```text
OpenDART
   |
   v
list metadata collection
   |
   v
durable discovery / processing state
   |
   v
disclosure content enrichment
   |
   v
DartEventTypeNormalizer
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
   |
   v
delivery to stock-market
   |
   v
market-session-aware event queue
   |
   v
EventCoordinator / event_reactive traders
```

The analyzer determines what an external disclosure appears to mean. The stock-market simulator remains responsible for deciding how many simulated traders react and what orders they generate.

---

## 2. Current State

The repository already has the following foundations.

- `OpenDartCollector` polls the OpenDART disclosure list.
- OpenDART `rcept_no` is retained as `provider_item_id`.
- Six-digit listed stock codes are retained in `RawNewsItem.symbols`.
- `provider_event_name` preserves the original DART report name.
- `SQLiteSeenItemStore` provides durable discovery deduplication.
- `CollectorPoller` provides repeated polling.
- `DartEventTypeNormalizer` converts DART report names into a stable `EventType`.
- `ClassificationInput`, `ClassificationDecision`, and `EventAssessmentModel` define a provider-neutral model boundary.
- Synthetic evaluation fixtures exist in `eval/classifier_cases.jsonl`.
- `MarketEvent` defines the downstream event payload.

The main missing piece is useful disclosure content. The list collector currently creates `RawNewsItem` values without a meaningful `body`, so a model would be asked to judge market impact from little more than the report title.

Model selection must therefore come after content enrichment and a realistic evaluation corpus.

---

## 3. Design Principles

### 3.1 Keep provider retrieval, domain normalization, and model inference separate

OpenDART-specific parsing must not leak into the model adapter.

The intended boundary is:

```text
provider document
   -> RawNewsItem.body
   -> EventType
   -> ClassificationInput
   -> EventAssessmentModel
```

A future provider should be able to reuse the same classification and delivery code.

### 3.2 Use rules for event type and the model for interpretation

The LLM should not rediscover structured facts already available from DART.

The normalizer owns:

- event type

The assessment model owns:

- direction: `BUY | SELL | MIXED`
- impact: `low | medium | high`
- confidence: `0.0 ... 1.0`

This keeps prompts smaller and makes provider/model comparisons easier.

### 3.3 Do not fabricate event timestamps

`detected_at` means when this process first observed the item.

If OpenDART does not provide an exact event timestamp, the analyzer must not silently pretend that `detected_at` is the actual occurrence time.

Before live `MarketEvent` composition is enabled, timestamp semantics must be made compatible with incomplete provider timestamps.

### 3.4 Analysis is 24/7; trading reaction is session-aware

The analyzer may collect and classify events while the simulated market is closed.

It must not suppress useful after-hours disclosures just because `stock-market` is closed.

The consumer decides whether the event is:

- immediately eligible,
- queued for the next market open,
- or stale and discarded.

### 3.5 A discovered item must not be lost because enrichment or inference failed

The current `SQLiteSeenItemStore.claim_unseen()` records discovery before later processing exists.

Once enrichment/model calls are connected, a single downstream failure must not permanently hide that disclosure.

The production path therefore needs durable processing state rather than discovery-only deduplication.

---

## 4. Target Processing State

The durable state should eventually distinguish discovery from successful processing.

A minimal lifecycle is:

```text
DISCOVERED
    |
    v
ENRICHED
    |
    v
CLASSIFIED
    |
    v
DELIVERED
```

Failures remain retryable:

```text
DISCOVERED -- enrichment failure --> DISCOVERED
ENRICHED   -- model/API failure  --> ENRICHED
CLASSIFIED -- delivery failure   --> CLASSIFIED
```

The implementation can continue to use SQLite for this personal-project scope.

The initial schema does not need a distributed queue, Kafka, Redis, or a workflow engine.

Suggested durable fields:

```text
provider
provider_item_id
first_detected_at
processing_state
attempt_count
last_error
updated_at
```

Model decisions or serialized `MarketEvent` payloads may be persisted later if retrying delivery without repeating model inference becomes useful.

---

## 5. Phase 1 — OpenDART Disclosure Content Enrichment

### Goal

Turn a metadata-only DART disclosure into model-useful text.

### Proposed boundary

Introduce a provider-specific content component without embedding model logic into it.

Possible shape:

```python
class DisclosureEnricher(Protocol):
    def enrich(self, item: RawNewsItem) -> RawNewsItem: ...
```

An OpenDART implementation uses `provider_item_id` / `rcept_no` to retrieve the disclosure document and returns a new `RawNewsItem` whose `body` contains cleaned text.

### Extraction rules

The first version should prefer useful, bounded text over perfect document reconstruction.

It should:

- preserve the headline and provider metadata,
- extract readable disclosure text,
- remove obvious navigation/boilerplate,
- normalize whitespace,
- avoid sending binary data or markup to the model,
- apply a deterministic maximum body size,
- keep enough numeric context for contracts, financing, earnings, dividends, and similar filings.

Do not add generic LLM summarization here. Enrichment should remain deterministic.

### Failure behavior

Document fetch or parsing failures must be explicit and retryable.

The initial enrichment component can be tested independently before it is placed behind durable processing state.

### Tests

Use checked-in provider-response fixtures or small synthetic document fixtures.

Cover at least:

- normal text extraction,
- tables/numeric content remaining readable,
- empty or malformed document,
- provider error,
- deterministic length limiting,
- preservation of `provider_item_id`, symbol, headline, and timestamps.

### Completion criteria

- representative OpenDART filings produce non-empty, readable `RawNewsItem.body`,
- provider parsing has no dependency on an LLM SDK,
- failure paths are deterministic and testable.

---

## 6. Phase 2 — Realistic Evaluation Corpus

### Goal

Create a small but useful benchmark before selecting a model.

The current synthetic cases remain valuable for schema and regression tests, but they are not enough to compare real disclosure interpretation quality.

### Initial corpus

Start with approximately 30–50 disclosures across several event types.

Suggested coverage:

- supply contract,
- capital increase,
- share buyback,
- dividend,
- earnings,
- merger/acquisition,
- lawsuit,
- debt financing / convertible securities,
- investment decision,
- ownership or management change,
- financial distress,
- ambiguous / other disclosures.

### Evaluation labels

Avoid pretending every disclosure has a single objectively correct short-term price direction.

Cases may define acceptable outputs where appropriate.

Example:

```json
{
  "event_type": "supply_contract",
  "acceptable_directions": ["BUY", "MIXED"],
  "acceptable_impacts": ["medium", "high"]
}
```

The corpus should also retain enough source text to reproduce the model input.

Do not include API secrets or private data.

### Metrics

At minimum record:

- structured-output/schema success rate,
- direction agreement,
- impact agreement,
- invalid/empty response rate,
- latency,
- token usage when available,
- estimated API cost.

Confidence should be inspected and calibrated later; it is not itself a correctness label.

### Completion criteria

- the same corpus can be run against multiple `EventAssessmentModel` implementations,
- results are machine-readable,
- model-specific prompt changes are versioned.

---

## 7. Phase 3 — Candidate Model Benchmark

### Goal

Choose a cost-effective model based on the actual enriched DART corpus rather than provider reputation.

Initial candidates may include DeepSeek and Kimi.

Exact model IDs, pricing, rate limits, and structured-output capabilities must be verified from current provider documentation at benchmark time.

### Benchmark runner

A benchmark command should:

```text
load eval cases
    |
    +--> model A adapter
    |
    +--> model B adapter
    |
    v
common result format
    |
    v
summary report
```

The benchmark code must not become the production pipeline.

### Selection criteria

Prefer a model that provides an acceptable balance of:

- schema reliability,
- direction/impact agreement,
- Korean disclosure comprehension,
- latency,
- cost,
- operational simplicity.

No provider is selected permanently in this phase. The repository should retain the model-neutral interface.

### Completion criteria

- at least two candidate configurations can run against the same corpus,
- results include cost/latency and classification-quality summaries,
- one default model/provider is documented for the next phase.

---

## 8. Phase 4 — Production EventAssessmentModel Adapter

### Goal

Implement the selected provider behind the existing `EventAssessmentModel` protocol.

Example shape:

```python
class ProviderAssessmentModel:
    def assess(
        self,
        item: ClassificationInput,
    ) -> ClassificationDecision:
        ...
```

### Requirements

- API key comes from environment only,
- request timeout is explicit,
- response schema is validated,
- invalid direction/impact/confidence is rejected,
- provider exceptions are translated into project-level errors,
- retry policy is bounded,
- logs never contain secrets,
- prompt/version information is identifiable for later evaluation.

The adapter must return only the domain `ClassificationDecision`.

### Completion criteria

- provider SDK/HTTP response types do not escape the adapter,
- malformed responses are covered by tests,
- evaluation fixtures can run through the same adapter used in production.

---

## 9. Phase 5 — Durable Analysis Pipeline and MarketEvent Composition

### Goal

Connect discovery, enrichment, normalization, inference, and event creation without losing work on transient failures.

Target:

```text
OpenDartCollector
      |
      v
DISCOVERED
      |
      v
enrichment
      |
      v
ENRICHED
      |
      v
DartEventTypeNormalizer
      |
      v
EventAssessmentModel
      |
      v
CLASSIFIED
      |
      v
MarketEvent
```

### Deduplication/state change

The current discovery-only `claim_unseen()` behavior must not be the sole retry mechanism.

Implement processing-state persistence or an equivalent two-phase design so that:

- provider duplicates do not create duplicate events,
- enrichment failures retry,
- model failures retry without recollecting metadata,
- successful classification does not need to be repeated just because downstream delivery failed.

### Timestamp contract

Before producing live `MarketEvent` values, resolve the mismatch between:

- exact `detected_at`,
- potentially unknown exact provider occurrence time,
- the current required `MarketEvent.occurred_at`.

Preferred rule:

> Unknown occurrence time is represented as unknown, not fabricated from detection time.

This may require making `occurred_at` optional or explicitly carrying provider date/time precision in the contract.

The chosen representation must be reflected in tests and in the stock-market ingest contract.

### Event identity

`event_id` must be deterministic for a provider disclosure.

A provider + source item ID derived identifier is preferred so retries cannot create multiple logical events.

### Completion criteria

- one newly discovered DART item can progress to a validated `MarketEvent`,
- restart/retry does not duplicate successful events,
- transient enrichment/model errors remain retryable,
- timestamp semantics are explicit.

---

## 10. Phase 6 — Delivery to stock-market

### Goal

Send normalized events into the simulator without coupling the analyzer to trader behavior.

For the initial project scale, use a simple HTTP boundary.

```text
market-event-analyzer
      |
      | JSON MarketEvent
      v
stock-market event ingest endpoint
      |
      v
durable/pending event state
      |
      v
EventCoordinator
```

Do not introduce Kafka, EventBridge, or another broker until there is a concrete need.

### Delivery requirements

- idempotency by `event_id`,
- explicit timeout,
- retry on transient delivery failure,
- no repeat model inference merely because delivery failed,
- clear 4xx vs 5xx handling,
- contract tests shared conceptually between repositories.

The analyzer sends interpretation only.

It does not send:

- activation ratios,
- order quantities,
- target RPS,
- trader counts.

Those remain stock-market simulation policy.

### Completion criteria

- one analyzer `MarketEvent` reaches stock-market exactly once logically despite retry,
- duplicate delivery is harmless,
- analyzer and simulator remain independently runnable.

---

## 11. Phase 7 — Market-Session-Aware Event Policy

### Goal

Define what stock-market does when a valid event arrives outside KST weekday 09:00–15:30.

The analyzer continues to ingest and classify events regardless of market state.

Suggested consumer policy:

```text
event arrives during OPEN
    -> eligible immediately

event arrives after close / before open
    -> store pending
    -> eligible at next market open

event becomes too old
    -> mark stale
    -> do not schedule reaction
```

### Policy values to define

- maximum stale age,
- whether stale age is measured from `occurred_at` or `detected_at` when occurrence time is unknown,
- ordering of multiple pending events,
- deduplication at market open,
- reaction spreading vs opening burst,
- treatment of weekend events.

A simple initial rule is preferable.

For example:

- retain after-hours events,
- release them at next open,
- drop events older than a fixed configured age,
- let existing `ReactionPlanner` determine simulated participant behavior.

### Important separation

The analyzer should not query the simulator's market state in order to decide whether an event is meaningful.

Market-session scheduling belongs to stock-market.

---

## 12. Phase 8 — Observability and Operations

Once live ingestion exists, add enough telemetry to answer:

```text
Did we discover it?
Did enrichment succeed?
Did the model classify it?
Did delivery succeed?
Was it queued for next open?
Did simulated traders react?
```

Candidate metrics:

```text
analyzer_items_discovered_total
analyzer_enrichment_attempts_total
analyzer_enrichment_failures_total
analyzer_classifications_total
analyzer_classification_failures_total
analyzer_delivery_attempts_total
analyzer_delivery_failures_total
analyzer_processing_backlog
analyzer_processing_age_seconds
```

Avoid model-provider labels with unbounded cardinality.

Logs should include provider item ID / event ID but never API keys or full sensitive request headers.

---

## 13. Implementation Order

The intended implementation sequence after this planning document is merged is:

1. OpenDART disclosure content enrichment.
2. Realistic DART evaluation corpus.
3. Candidate-model benchmark tooling.
4. Selected `EventAssessmentModel` provider adapter.
5. Durable processing state + `MarketEvent` composition.
6. HTTP delivery to stock-market.
7. Off-hours / next-open event policy in stock-market.
8. Observability and runbook polish.

Each step should remain a focused PR where possible.

Do not combine provider parsing, model selection, delivery, and market-session policy into one change.

---

## 14. Non-Goals

The first complete version does not need:

- brokerage integration,
- real-money trading,
- tick-by-tick price prediction,
- exact future-return forecasting,
- fine-tuning a custom language model,
- vector databases,
- Kafka/EventBridge,
- distributed workers,
- multi-region failover,
- perfect reconstruction of every DART attachment,
- every Korean disclosure category,
- automated investment recommendations.

The project goal is to generate plausible, reproducible event-driven workload for infrastructure experiments.

---

## 15. Final Completion Criteria

The event-analysis integration is complete when all of the following are true:

- OpenDART disclosures are collected without duplicates.
- Useful disclosure content is available to classification.
- A realistic evaluation corpus exists.
- A selected model adapter satisfies the model-neutral interface.
- Invalid model output is rejected deterministically.
- Processing failures remain retryable after process restart.
- A disclosure produces a deterministic, validated `MarketEvent`.
- Unknown exact occurrence time is not silently fabricated.
- Delivery to stock-market is idempotent.
- Analyzer can continue operating while the simulated market is closed.
- After-hours events can be held and released according to an explicit next-open/stale policy.
- Event-reactive traders receive normalized events without analyzer-side trader/order policy.
- Metrics and logs make discovery, classification, delivery, and pending-event failures diagnosable.

At that point, model tuning and more realistic event-reaction experiments can proceed without changing the core boundaries.
