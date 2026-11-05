from datetime import datetime, timezone
import json
from urllib.error import HTTPError, URLError

import pytest

from market_event_analyzer.classification import ClassificationDecision, EventType
from market_event_analyzer.composition import compose_market_event
from market_event_analyzer.contract import Direction, Impact
from market_event_analyzer.delivery import (
    DurableDeliveryWorker,
    HttpMarketEventDelivery,
    MarketEventDeliveryError,
)
from market_event_analyzer.news import RawNewsItem
from market_event_analyzer.processing import ProcessingState, SQLiteProcessingStore


NOW = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)


def make_classified_store(tmp_path):
    item = RawNewsItem(
        provider="opendart",
        provider_item_id="20260928000123",
        headline="삼성전자: 단일판매ㆍ공급계약체결",
        detected_at=NOW,
        body="공시 본문",
        symbols=("005930",),
        provider_event_name="단일판매ㆍ공급계약체결",
    )
    decision = ClassificationDecision(
        direction=Direction.BUY,
        impact=Impact.HIGH,
        confidence=0.85,
    )
    event = compose_market_event(
        item,
        EventType.SUPPLY_CONTRACT,
        decision,
    )
    store = SQLiteProcessingStore(
        tmp_path / "processing.sqlite3",
        clock=lambda: NOW,
    )
    store.discover((item,))
    store.mark_enriched(item, EventType.SUPPLY_CONTRACT)
    store.mark_classified(item, event)
    return store, item, event


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_http_delivery_posts_market_event_json():
    captured = {}

    def open_url(request, **kwargs):
        captured["request"] = request
        captured["kwargs"] = kwargs
        return FakeResponse(201)

    event = compose_market_event(
        RawNewsItem(
            provider="opendart",
            provider_item_id="20260928000123",
            headline="공시",
            detected_at=NOW,
            body="본문",
            symbols=("005930",),
        ),
        EventType.OTHER,
        ClassificationDecision(
            direction=Direction.MIXED,
            impact=Impact.MEDIUM,
            confidence=0.61,
        ),
    )

    HttpMarketEventDelivery(
        "http://stock-market/api/v1/events/",
        timeout_seconds=7,
        open_url=open_url,
    ).deliver(event)

    assert captured["request"].full_url == "http://stock-market/api/v1/events/"
    assert captured["request"].method == "POST"
    assert captured["request"].headers["Content-type"] == "application/json"
    assert json.loads(captured["request"].data)["event_id"] == event.event_id
    assert captured["kwargs"]["timeout"] == 7


@pytest.mark.parametrize("status", [200, 201, 202, 204])
def test_http_delivery_accepts_any_2xx(status):
    delivery = HttpMarketEventDelivery(
        "http://stock-market/api/v1/events/",
        open_url=lambda request, **kwargs: FakeResponse(status),
    )

    item = RawNewsItem(
        provider="opendart",
        provider_item_id="20260928000123",
        headline="공시",
        detected_at=NOW,
        symbols=("005930",),
    )
    event = compose_market_event(
        item,
        EventType.OTHER,
        ClassificationDecision(
            direction=Direction.BUY,
            impact=Impact.LOW,
            confidence=0.5,
        ),
    )
    delivery.deliver(event)


def test_http_delivery_translates_http_and_network_errors():
    item = RawNewsItem(
        provider="opendart",
        provider_item_id="20260928000123",
        headline="공시",
        detected_at=NOW,
        symbols=("005930",),
    )
    event = compose_market_event(
        item,
        EventType.OTHER,
        ClassificationDecision(
            direction=Direction.BUY,
            impact=Impact.LOW,
            confidence=0.5,
        ),
    )

    def http_error(request, **kwargs):
        raise HTTPError(request.full_url, 409, "conflict", None, None)

    def network_error(request, **kwargs):
        raise URLError("offline")

    with pytest.raises(MarketEventDeliveryError, match="HTTP 409"):
        HttpMarketEventDelivery("http://stock/events/", open_url=http_error).deliver(event)

    with pytest.raises(MarketEventDeliveryError, match="offline"):
        HttpMarketEventDelivery("http://stock/events/", open_url=network_error).deliver(event)


def test_delivery_success_logs_injected_event(tmp_path, caplog):
    store, _item, event = make_classified_store(tmp_path)
    worker = DurableDeliveryWorker(
        store,
        HttpMarketEventDelivery(
            "http://stock/events/",
            open_url=lambda request, **kwargs: FakeResponse(201),
        ),
    )

    with caplog.at_level("INFO"):
        worker.run_once()

    assert "event=event_delivered" in caplog.text
    assert f"event_id={event.event_id}" in caplog.text
    assert f"symbol={event.symbol}" in caplog.text
    assert f"direction={event.direction.value}" in caplog.text
    assert f"impact={event.impact.value}" in caplog.text


def test_delivery_success_marks_event_delivered(tmp_path):
    store, item, event = make_classified_store(tmp_path)
    worker = DurableDeliveryWorker(
        store,
        HttpMarketEventDelivery(
            "http://stock/events/",
            open_url=lambda request, **kwargs: FakeResponse(201),
        ),
    )

    result = worker.run_once()

    assert result.attempted_count == 1
    assert result.delivered_count == 1
    assert result.failed_count == 0
    assert result.delivered_event_ids == (event.event_id,)
    assert store.get_record(
        item.provider,
        item.provider_item_id,
    ).state is ProcessingState.DELIVERED
    assert store.classified_events() == ()


def test_delivery_failure_stays_classified_and_retries_without_model_work(tmp_path):
    store, item, event = make_classified_store(tmp_path)
    calls = 0

    def open_url(request, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise URLError("temporary outage")
        return FakeResponse(200)

    worker = DurableDeliveryWorker(
        store,
        HttpMarketEventDelivery(
            "http://stock/events/",
            open_url=open_url,
        ),
    )

    first = worker.run_once()
    first_record = store.get_record(item.provider, item.provider_item_id)
    assert first.failed_count == 1
    assert first_record.state is ProcessingState.CLASSIFIED
    assert first_record.attempt_count == 1
    assert first_record.event == event

    second = worker.run_once()
    assert second.delivered_count == 1
    assert calls == 2
    assert store.get_record(
        item.provider,
        item.provider_item_id,
    ).state is ProcessingState.DELIVERED


def test_delivered_event_is_not_sent_again(tmp_path):
    store, item, _ = make_classified_store(tmp_path)
    calls = 0

    def open_url(request, **kwargs):
        nonlocal calls
        calls += 1
        return FakeResponse(201)

    worker = DurableDeliveryWorker(
        store,
        HttpMarketEventDelivery(
            "http://stock/events/",
            open_url=open_url,
        ),
    )

    worker.run_once()
    second = worker.run_once()

    assert calls == 1
    assert second.attempted_count == 0
