from datetime import date, datetime
import json
from zoneinfo import ZoneInfo

from market_event_analyzer.classification import EventType
from market_event_analyzer.corpus import (
    build_dart_corpus_candidates,
    write_draft_cases,
)
from market_event_analyzer.news import RawNewsItem


SEOUL = ZoneInfo("Asia/Seoul")


def item(receipt: str, report_name: str, symbol: str = "005930") -> RawNewsItem:
    return RawNewsItem(
        provider="opendart",
        provider_item_id=receipt,
        headline=f"테스트회사: {report_name}",
        detected_at=datetime(2026, 9, 22, 18, 0, tzinfo=SEOUL),
        symbols=(symbol,),
        provider_event_name=report_name,
        url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}",
    )


class FakeCollector:
    def __init__(self, items):
        self.items = tuple(items)
        self.calls = []

    def collect_range(self, start_date, end_date):
        self.calls.append((start_date, end_date))
        return self.items


class FakeEnricher:
    def __init__(self, failures=()):
        self.failures = set(failures)
        self.calls = []

    def enrich(self, raw):
        self.calls.append(raw.provider_item_id)
        if raw.provider_item_id in self.failures:
            raise RuntimeError("boom")
        return RawNewsItem(
            provider=raw.provider,
            provider_item_id=raw.provider_item_id,
            headline=raw.headline,
            detected_at=raw.detected_at,
            published_at=raw.published_at,
            body=f"본문 {raw.provider_item_id}",
            url=raw.url,
            symbols=raw.symbols,
            provider_event_name=raw.provider_event_name,
        )


def test_builder_balances_event_types_before_enrichment() -> None:
    collector = FakeCollector(
        (
            item("20260922000001", "단일판매ㆍ공급계약체결"),
            item("20260922000002", "단일판매ㆍ공급계약체결"),
            item("20260922000003", "유상증자결정"),
            item("20260922000004", "현금ㆍ현물배당결정"),
        )
    )
    enricher = FakeEnricher()

    result = build_dart_corpus_candidates(
        collector,
        enricher,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 22),
        limit=10,
        max_per_event_type=1,
    )

    assert collector.calls == [(date(2026, 9, 1), date(2026, 9, 22))]
    assert enricher.calls == [
        "20260922000001",
        "20260922000003",
        "20260922000004",
    ]
    assert [case.event_type for case in result.cases] == [
        EventType.SUPPLY_CONTRACT,
        EventType.CAPITAL_INCREASE,
        EventType.DIVIDEND,
    ]


def test_builder_records_enrichment_failures_and_continues() -> None:
    collector = FakeCollector(
        (
            item("20260922000001", "단일판매ㆍ공급계약체결"),
            item("20260922000002", "유상증자결정"),
        )
    )
    enricher = FakeEnricher(failures=("20260922000001",))

    result = build_dart_corpus_candidates(
        collector,
        enricher,
        start_date=date(2026, 9, 22),
        end_date=date(2026, 9, 22),
    )

    assert result.attempted_enrichments == 2
    assert result.failed_enrichments == ("20260922000001",)
    assert [case.source_item_id for case in result.cases] == ["20260922000002"]


def test_builder_can_exclude_other_event_type() -> None:
    collector = FakeCollector(
        (
            item("20260922000001", "정체불명공시"),
            item("20260922000002", "소송등의제기ㆍ신청"),
        )
    )

    result = build_dart_corpus_candidates(
        collector,
        FakeEnricher(),
        start_date=date(2026, 9, 22),
        end_date=date(2026, 9, 22),
        include_other=False,
    )

    assert [case.event_type for case in result.cases] == [EventType.LAWSUIT]


def test_writer_outputs_review_pending_jsonl(tmp_path) -> None:
    collector = FakeCollector(
        (item("20260922000001", "단일판매ㆍ공급계약체결"),)
    )
    result = build_dart_corpus_candidates(
        collector,
        FakeEnricher(),
        start_date=date(2026, 9, 22),
        end_date=date(2026, 9, 22),
    )
    output = tmp_path / "draft.jsonl"

    write_draft_cases(output, result.cases)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["case_id"] == "opendart_20260922000001"
    assert payload["provider"] == "opendart"
    assert payload["source_item_id"] == "20260922000001"
    assert payload["acceptable_directions"] == []
    assert payload["acceptable_impacts"] == []
    assert payload["review_status"] == "pending"
