#!/usr/bin/env python3
import argparse
import os
from pathlib import Path

from market_event_analyzer.delivery import (
    DurableDeliveryWorker,
    HttpMarketEventDelivery,
)
from market_event_analyzer.processing import SQLiteProcessingStore


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deliver persisted CLASSIFIED MarketEvents to stock-market."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/processing.sqlite3"),
    )
    parser.add_argument(
        "--endpoint",
        default=os.getenv(
            "STOCK_MARKET_EVENT_URL",
            "http://127.0.0.1:8000/api/v1/events/",
        ),
    )
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    args = parser.parse_args()

    store = SQLiteProcessingStore(args.database)
    worker = DurableDeliveryWorker(
        store,
        HttpMarketEventDelivery(
            args.endpoint,
            timeout_seconds=args.timeout_seconds,
        ),
    )
    result = worker.run_once()

    for failure in result.failures:
        print(
            f"FAILED {failure.provider}:{failure.provider_item_id} "
            f"state={failure.state.value} {failure.error}",
            flush=True,
        )

    print(
        f"delivery attempted={result.attempted_count} "
        f"delivered={result.delivered_count} "
        f"failed={result.failed_count}",
        flush=True,
    )
    return 1 if result.failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
