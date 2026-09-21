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

`AnalysisPipeline` only orchestrates those two interfaces. It does not know whether collection comes from a fixture, DART, or a news API, and it does not know whether classification is rule-based, LLM-based, or hybrid.

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

The next milestone is one real collector adapter. Classifier implementation and delivery to `stock-market` remain separate follow-up steps.
