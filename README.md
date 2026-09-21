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
EventClassifier
      |
      v
MarketEvent
```

`AnalysisPipeline` only orchestrates those two interfaces. It does not know whether collection comes from a fixture, OpenDART, or a news API, and it does not know whether classification is rule-based, LLM-based, or hybrid.

## OpenDART collector

`OpenDartCollector` queries the OpenDART disclosure list for the current Korea date, follows all result pages, and emits listed-company disclosures as `RawNewsItem` values.

OpenDART provides the filing date but not an exact filing timestamp in the list response. The collector therefore leaves `published_at` unknown and records the exact time this process first observed the disclosure in `detected_at`.

The provider-supplied six-digit stock code is preserved in `RawNewsItem.symbols` instead of being inferred again later.

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

Example:

```python
from market_event_analyzer import (
    CollectorPoller,
    DeduplicatingCollector,
    SQLiteSeenItemStore,
)
from market_event_analyzer.providers import OpenDartCollector

collector = DeduplicatingCollector(
    OpenDartCollector.from_env(),
    SQLiteSeenItemStore("state/seen.sqlite3"),
)
poller = CollectorPoller(collector, interval_seconds=30)

poller.run(lambda items: print(items))
```

At this milestone, deduplication means an item is marked seen when it is emitted by the deduplicating collector. A later delivery/retry milestone can introduce acknowledged processing if downstream classifier failures need at-least-once semantics.

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

The next milestone is classification: first map disclosure types into stable event categories, then add BUY/SELL/MIXED, impact, and confidence inference behind the existing `EventClassifier` interface.
