from datetime import datetime
import os
from zoneinfo import ZoneInfo

import pytest

from market_event_analyzer.providers.opendart import (
    DART_VIEWER_URL,
    OPEN_DART_LIST_URL,
    OpenDartAPIError,
    OpenDartCollector,
)


SEOUL = ZoneInfo("Asia/Seoul")


def fixed_now() -> datetime:
    return datetime(2026, 9, 21, 18, 30, tzinfo=SEOUL)


def test_collector_converts_listed_disclosures_and_skips_unlisted_companies() -> None:
    calls = []

    def fetch_json(url, params):
        calls.append((url, dict(params)))
        return {
            "status": "000",
            "message": "정상",
            "total_page": 1,
            "list": [
                {
                    "corp_name": "삼성전자",
                    "stock_code": "005930",
                    "report_nm": "단일판매ㆍ공급계약체결",
                    "rcept_no": "20260921000123",
                    "rcept_dt": "20260921",
                },
                {
                    "corp_name": "비상장회사",
                    "stock_code": "",
                    "report_nm": "주요사항보고서",
                    "rcept_no": "20260921000456",
                    "rcept_dt": "20260921",
                },
            ],
        }

    items = OpenDartCollector(
        "test-key",
        fetch_json=fetch_json,
        clock=fixed_now,
    ).collect()

    assert len(items) == 1
    item = items[0]
    assert item.provider == "opendart"
    assert item.provider_item_id == "20260921000123"
    assert item.headline == "삼성전자: 단일판매ㆍ공급계약체결"
    assert item.symbols == ("005930",)
    assert item.published_at is None
    assert item.detected_at == fixed_now()
    assert item.url == DART_VIEWER_URL.format(rcept_no="20260921000123")

    assert calls == [
        (
            OPEN_DART_LIST_URL,
            {
                "crtfc_key": "test-key",
                "bgn_de": "20260921",
                "end_de": "20260921",
                "sort": "date",
                "sort_mth": "asc",
                "page_no": "1",
                "page_count": "100",
            },
        )
    ]


def test_collector_reads_all_pages() -> None:
    pages = []

    def fetch_json(url, params):
        page = int(params["page_no"])
        pages.append(page)
        return {
            "status": "000",
            "message": "정상",
            "total_page": 2,
            "list": [
                {
                    "corp_name": f"회사{page}",
                    "stock_code": f"00000{page}",
                    "report_nm": "공시",
                    "rcept_no": f"2026092100000{page}",
                }
            ],
        }

    items = OpenDartCollector(
        "test-key",
        fetch_json=fetch_json,
        clock=fixed_now,
    ).collect()

    assert pages == [1, 2]
    assert [item.provider_item_id for item in items] == [
        "20260921000001",
        "20260921000002",
    ]


def test_no_data_status_returns_empty_tuple() -> None:
    def fetch_json(url, params):
        return {"status": "013", "message": "조회된 데이타가 없습니다."}

    items = OpenDartCollector(
        "test-key",
        fetch_json=fetch_json,
        clock=fixed_now,
    ).collect()

    assert items == ()


def test_api_error_is_not_silently_ignored() -> None:
    def fetch_json(url, params):
        return {"status": "020", "message": "요청 제한을 초과하였습니다."}

    with pytest.raises(OpenDartAPIError) as exc_info:
        OpenDartCollector(
            "test-key",
            fetch_json=fetch_json,
            clock=fixed_now,
        ).collect()

    assert exc_info.value.status == "020"


def test_from_env_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENDART_API_KEY"):
        OpenDartCollector.from_env(clock=fixed_now)


def test_from_env_reads_api_key(monkeypatch) -> None:
    monkeypatch.setenv("OPENDART_API_KEY", "env-key")

    captured = {}

    def fetch_json(url, params):
        captured["key"] = params["crtfc_key"]
        return {"status": "013", "message": "조회된 데이타가 없습니다."}

    OpenDartCollector.from_env(
        fetch_json=fetch_json,
        clock=fixed_now,
    ).collect()

    assert captured["key"] == "env-key"
