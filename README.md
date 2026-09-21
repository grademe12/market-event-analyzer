# market-event-analyzer

Financial news and disclosure events normalized into a small market-event contract.

This project is intentionally separate from `stock-market`.

- **market-event-analyzer** collects and analyzes external news/disclosures.
- **stock-market** consumes normalized events and decides how simulated traders react.
- This project does **not** place real brokerage orders.

The first implementation milestone is a stable output contract that can later be produced by fixtures, rule-based classifiers, or LLM-based classifiers.
