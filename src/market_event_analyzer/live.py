from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
from threading import Event
from typing import Protocol

from market_event_analyzer.delivery import (
    DeliveryCycleResult,
    DurableDeliveryWorker,
    HttpMarketEventDelivery,
)
from market_event_analyzer.kiro_model import (
    DEFAULT_AGENT_NAME,
    DEFAULT_TIMEOUT_SECONDS,
    KiroAssessmentModel,
)
from market_event_analyzer.news import RawNewsItem
from market_event_analyzer.normalizers import DartEventTypeNormalizer
from market_event_analyzer.processing import (
    DurableAnalysisPipeline,
    ProcessingCycleResult,
    SQLiteProcessingStore,
)
from market_event_analyzer.providers.opendart import OpenDartCollector
from market_event_analyzer.providers.opendart_document import OpenDartDisclosureEnricher


DEFAULT_POLL_SECONDS = 60.0
DEFAULT_DATABASE_PATH = Path("data/processing.sqlite3")
DEFAULT_STOCK_MARKET_EVENT_URL = "http://127.0.0.1:8000/api/v1/events/"
DEFAULT_DELIVERY_TIMEOUT_SECONDS = 10.0


class Collector(Protocol):
    def collect(self) -> tuple[RawNewsItem, ...]: ...


class AnalysisRunner(Protocol):
    def run_once(self) -> ProcessingCycleResult: ...


class DeliveryRunner(Protocol):
    def run_once(self) -> DeliveryCycleResult: ...


@dataclass(frozen=True, slots=True)
class LiveConfig:
    opendart_api_key: str
    kiro_api_key: str
    database_path: Path
    stock_market_event_url: str
    poll_seconds: float
    kiro_cli_path: str
    kiro_agent_name: str
    kiro_timeout_seconds: float
    delivery_timeout_seconds: float
    working_directory: Path
    symbols: tuple[str, ...]

    @classmethod
    def from_environment(cls) -> "LiveConfig":
        opendart_api_key = _required_env("OPENDART_API_KEY")
        kiro_api_key = _required_env("KIRO_API_KEY")
        stock_market_event_url = os.getenv(
            "STOCK_MARKET_EVENT_URL",
            DEFAULT_STOCK_MARKET_EVENT_URL,
        ).strip()
        if not stock_market_event_url:
            raise ValueError("STOCK_MARKET_EVENT_URL must not be blank")

        return cls(
            opendart_api_key=opendart_api_key,
            kiro_api_key=kiro_api_key,
            database_path=Path(
                os.getenv("MARKET_EVENT_DATABASE", str(DEFAULT_DATABASE_PATH))
            ).expanduser(),
            stock_market_event_url=stock_market_event_url,
            poll_seconds=_positive_float(
                "MARKET_EVENT_POLL_SECONDS",
                DEFAULT_POLL_SECONDS,
            ),
            kiro_cli_path=os.getenv("KIRO_CLI_PATH", "kiro-cli").strip()
            or "kiro-cli",
            kiro_agent_name=os.getenv(
                "KIRO_AGENT_NAME",
                DEFAULT_AGENT_NAME,
            ).strip()
            or DEFAULT_AGENT_NAME,
            kiro_timeout_seconds=_positive_float(
                "KIRO_TIMEOUT_SECONDS",
                DEFAULT_TIMEOUT_SECONDS,
            ),
            delivery_timeout_seconds=_positive_float(
                "STOCK_MARKET_TIMEOUT_SECONDS",
                DEFAULT_DELIVERY_TIMEOUT_SECONDS,
            ),
            working_directory=Path(
                os.getenv("MARKET_EVENT_WORKDIR", str(Path.cwd()))
            ).expanduser().resolve(),
            symbols=_parse_symbols(os.getenv("MARKET_EVENT_SYMBOLS", "")),
        )


@dataclass(frozen=True, slots=True)
class LiveCycleResult:
    analysis: ProcessingCycleResult | None
    delivery: DeliveryCycleResult | None
    analysis_error: str = ""
    delivery_error: str = ""


class SymbolFilteringCollector:
    def __init__(
        self,
        collector: Collector,
        symbols: tuple[str, ...],
    ) -> None:
        self._collector = collector
        self._symbols = frozenset(symbols)

    def collect(self) -> tuple[RawNewsItem, ...]:
        items = self._collector.collect()
        if not self._symbols:
            return items
        return tuple(
            item
            for item in items
            if any(symbol in self._symbols for symbol in item.symbols)
        )


class ResilientCollector:
    """Keep stored retries moving even if the provider poll is temporarily down."""

    def __init__(self, collector: Collector) -> None:
        self._collector = collector

    def collect(self) -> tuple[RawNewsItem, ...]:
        try:
            return self._collector.collect()
        except Exception:
            logging.exception(
                "event=collector_failed provider=opendart "
                "action=continue_with_stored_work"
            )
            return ()


class LiveWorker:
    def __init__(
        self,
        analysis: AnalysisRunner,
        delivery: DeliveryRunner,
        *,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self._analysis = analysis
        self._delivery = delivery
        self._poll_seconds = poll_seconds

    def run_cycle(self) -> LiveCycleResult:
        analysis_result: ProcessingCycleResult | None = None
        delivery_result: DeliveryCycleResult | None = None
        analysis_error = ""
        delivery_error = ""

        try:
            analysis_result = self._analysis.run_once()
            logging.info(
                "event=analysis_cycle collected=%s discovered=%s enriched=%s "
                "classified=%s failed=%s",
                analysis_result.collected_count,
                analysis_result.discovered_count,
                analysis_result.enriched_count,
                analysis_result.classified_count,
                analysis_result.failed_count,
            )
            for failure in analysis_result.failures:
                logging.warning(
                    "event=analysis_item_failed provider=%s source_item_id=%s "
                    "state=%s error=%s",
                    failure.provider,
                    failure.provider_item_id,
                    failure.state.value,
                    failure.error,
                )
        except Exception as exc:
            analysis_error = f"{type(exc).__name__}: {exc}"
            logging.exception("event=analysis_cycle_failed")

        try:
            delivery_result = self._delivery.run_once()
            logging.info(
                "event=delivery_cycle attempted=%s delivered=%s failed=%s",
                delivery_result.attempted_count,
                delivery_result.delivered_count,
                delivery_result.failed_count,
            )
            for failure in delivery_result.failures:
                logging.warning(
                    "event=delivery_item_failed provider=%s source_item_id=%s "
                    "state=%s error=%s",
                    failure.provider,
                    failure.provider_item_id,
                    failure.state.value,
                    failure.error,
                )
        except Exception as exc:
            delivery_error = f"{type(exc).__name__}: {exc}"
            logging.exception("event=delivery_cycle_failed")

        return LiveCycleResult(
            analysis=analysis_result,
            delivery=delivery_result,
            analysis_error=analysis_error,
            delivery_error=delivery_error,
        )

    def run_forever(self, stop_event: Event) -> None:
        while not stop_event.is_set():
            self.run_cycle()
            if stop_event.wait(self._poll_seconds):
                break


def build_live_worker(config: LiveConfig) -> LiveWorker:
    collector: Collector = OpenDartCollector(config.opendart_api_key)
    collector = SymbolFilteringCollector(collector, config.symbols)
    collector = ResilientCollector(collector)

    store = SQLiteProcessingStore(config.database_path)
    analysis = DurableAnalysisPipeline(
        collector,
        OpenDartDisclosureEnricher(config.opendart_api_key),
        DartEventTypeNormalizer(),
        KiroAssessmentModel(
            cli_path=config.kiro_cli_path,
            agent_name=config.kiro_agent_name,
            timeout_seconds=config.kiro_timeout_seconds,
            working_directory=config.working_directory,
        ),
        store,
    )
    delivery = DurableDeliveryWorker(
        store,
        HttpMarketEventDelivery(
            config.stock_market_event_url,
            timeout_seconds=config.delivery_timeout_seconds,
        ),
    )
    return LiveWorker(
        analysis,
        delivery,
        poll_seconds=config.poll_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Continuously analyze OpenDART disclosures and deliver MarketEvents."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="run one analysis + delivery cycle and exit",
    )
    args = parser.parse_args(argv)

    _configure_logging()

    try:
        config = LiveConfig.from_environment()
        worker = build_live_worker(config)
    except Exception as exc:
        logging.error("live worker startup failed: %s", exc)
        return 1

    if config.symbols:
        logging.info(
            "event=live_worker_start poll_seconds=%s database=%s symbols=%s endpoint=%s",
            config.poll_seconds,
            config.database_path,
            ",".join(config.symbols),
            config.stock_market_event_url,
        )
    else:
        logging.warning(
            "event=live_worker_start poll_seconds=%s database=%s symbols=ALL "
            "endpoint=%s note=all_listed_disclosures_will_be_analyzed",
            config.poll_seconds,
            config.database_path,
            config.stock_market_event_url,
        )

    if args.once:
        result = worker.run_cycle()
        return 1 if result.analysis_error or result.delivery_error else 0

    stop_event = Event()

    def request_stop(*_args: object) -> None:
        logging.info("event=live_worker_stop_requested")
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    worker.run_forever(stop_event)
    logging.info("event=live_worker_stopped")
    return 0


def _configure_logging() -> None:
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)

    log_dir = Path(os.getenv("MARKET_EVENT_LOG_DIR", "logs")).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "analyzer.log",
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is not set")
    return value


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _parse_symbols(raw: str) -> tuple[str, ...]:
    symbols = tuple(
        dict.fromkeys(
            value.strip()
            for value in raw.split(",")
            if value.strip()
        )
    )
    invalid = [
        symbol
        for symbol in symbols
        if len(symbol) != 6 or not symbol.isdigit()
    ]
    if invalid:
        raise ValueError(
            "MARKET_EVENT_SYMBOLS must contain comma-separated six-digit stock codes"
        )
    return symbols
