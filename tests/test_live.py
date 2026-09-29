from datetime import datetime, timezone
from threading import Event

import pytest

from market_event_analyzer.delivery import DeliveryCycleResult
from market_event_analyzer.live import (
    LiveConfig,
    LiveWorker,
    ResilientCollector,
    SymbolFilteringCollector,
)
from market_event_analyzer.news import RawNewsItem
from market_event_analyzer.processing import ProcessingCycleResult


NOW = datetime(2026, 9, 29, 9, 0, tzinfo=timezone.utc)


def item(symbol: str, item_id: str) -> RawNewsItem:
    return RawNewsItem(
        provider="opendart",
        provider_item_id=item_id,
        headline="공시",
        detected_at=NOW,
        symbols=(symbol,),
    )


class StaticCollector:
    def __init__(self, items):
        self.items = tuple(items)

    def collect(self):
        return self.items


class FailingCollector:
    def collect(self):
        raise RuntimeError("provider unavailable")


class FakeAnalysis:
    def __init__(self, *, error=None):
        self.calls = 0
        self.error = error

    def run_once(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ProcessingCycleResult(
            collected_count=1,
            discovered_count=1,
            enriched_count=1,
            classified_count=1,
            failed_count=0,
            events=(),
            failures=(),
        )


class FakeDelivery:
    def __init__(self, *, error=None):
        self.calls = 0
        self.error = error

    def run_once(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return DeliveryCycleResult(
            attempted_count=1,
            delivered_count=1,
            failed_count=0,
            delivered_event_ids=("event-1",),
            failures=(),
        )


def test_symbol_filtering_collector_keeps_only_selected_symbols():
    collector = SymbolFilteringCollector(
        StaticCollector(
            (
                item("005930", "1"),
                item("000660", "2"),
                item("035420", "3"),
            )
        ),
        ("005930", "035420"),
    )

    result = collector.collect()

    assert [entry.symbols[0] for entry in result] == ["005930", "035420"]


def test_empty_symbol_filter_keeps_all_items():
    source = (item("005930", "1"), item("000660", "2"))

    result = SymbolFilteringCollector(
        StaticCollector(source),
        (),
    ).collect()

    assert result == source


def test_resilient_collector_converts_provider_failure_to_empty_batch(caplog):
    collector = ResilientCollector(FailingCollector())

    assert collector.collect() == ()
    assert "collector_failed" in caplog.text


def test_live_cycle_runs_delivery_even_when_analysis_crashes():
    analysis = FakeAnalysis(error=RuntimeError("analysis boom"))
    delivery = FakeDelivery()
    worker = LiveWorker(analysis, delivery, poll_seconds=1)

    result = worker.run_cycle()

    assert analysis.calls == 1
    assert delivery.calls == 1
    assert result.analysis is None
    assert result.delivery is not None
    assert "analysis boom" in result.analysis_error


def test_live_cycle_keeps_running_when_delivery_crashes():
    analysis = FakeAnalysis()
    delivery = FakeDelivery(error=RuntimeError("delivery boom"))
    worker = LiveWorker(analysis, delivery, poll_seconds=1)

    result = worker.run_cycle()

    assert analysis.calls == 1
    assert delivery.calls == 1
    assert result.analysis is not None
    assert result.delivery is None
    assert "delivery boom" in result.delivery_error


def test_run_forever_honors_stop_event_without_extra_cycle():
    analysis = FakeAnalysis()
    delivery = FakeDelivery()
    worker = LiveWorker(analysis, delivery, poll_seconds=60)
    stop_event = Event()
    stop_event.set()

    worker.run_forever(stop_event)

    assert analysis.calls == 0
    assert delivery.calls == 0


def test_live_config_reads_runtime_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENDART_API_KEY", "dart-key")
    monkeypatch.setenv("KIRO_API_KEY", "kiro-key")
    monkeypatch.setenv("MARKET_EVENT_DATABASE", str(tmp_path / "state.sqlite3"))
    monkeypatch.setenv("MARKET_EVENT_POLL_SECONDS", "30")
    monkeypatch.setenv("MARKET_EVENT_SYMBOLS", "005930,000660,005930")
    monkeypatch.setenv("STOCK_MARKET_EVENT_URL", "http://gateway:8000/api/v1/events/")
    monkeypatch.setenv("KIRO_CLI_PATH", "/opt/kiro/bin/kiro-cli")
    monkeypatch.setenv("MARKET_EVENT_WORKDIR", str(tmp_path))

    config = LiveConfig.from_environment()

    assert config.opendart_api_key == "dart-key"
    assert config.kiro_api_key == "kiro-key"
    assert config.database_path == tmp_path / "state.sqlite3"
    assert config.poll_seconds == 30
    assert config.symbols == ("005930", "000660")
    assert config.stock_market_event_url == "http://gateway:8000/api/v1/events/"
    assert config.kiro_cli_path == "/opt/kiro/bin/kiro-cli"
    assert config.working_directory == tmp_path.resolve()


@pytest.mark.parametrize("raw", ["5930", "ABCDEF", "005930,123"])
def test_live_config_rejects_invalid_symbol_filter(monkeypatch, raw):
    monkeypatch.setenv("OPENDART_API_KEY", "dart-key")
    monkeypatch.setenv("KIRO_API_KEY", "kiro-key")
    monkeypatch.setenv("MARKET_EVENT_SYMBOLS", raw)

    with pytest.raises(ValueError, match="six-digit"):
        LiveConfig.from_environment()
