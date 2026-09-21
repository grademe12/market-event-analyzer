from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import json
import os
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from market_event_analyzer.news import RawNewsItem


OPEN_DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
SEOUL = ZoneInfo("Asia/Seoul")

JsonFetcher = Callable[[str, Mapping[str, str]], Mapping[str, Any]]
Clock = Callable[[], datetime]


class OpenDartAPIError(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(f"OpenDART error {status}: {message}")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _fetch_json(url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
    request_url = f"{url}?{urlencode(params)}"
    with urlopen(request_url, timeout=10) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("OpenDART response must be a JSON object")
    return payload


class OpenDartCollector:
    def __init__(
        self,
        api_key: str,
        *,
        fetch_json: JsonFetcher = _fetch_json,
        clock: Clock = _utc_now,
        page_count: int = 100,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key must not be blank")
        if not 1 <= page_count <= 100:
            raise ValueError("page_count must be between 1 and 100")
        self._api_key = api_key
        self._fetch_json = fetch_json
        self._clock = clock
        self._page_count = page_count

    @classmethod
    def from_env(
        cls,
        *,
        fetch_json: JsonFetcher = _fetch_json,
        clock: Clock = _utc_now,
        page_count: int = 100,
    ) -> "OpenDartCollector":
        api_key = os.getenv("OPENDART_API_KEY", "")
        if not api_key.strip():
            raise RuntimeError("OPENDART_API_KEY is not set")
        return cls(
            api_key,
            fetch_json=fetch_json,
            clock=clock,
            page_count=page_count,
        )

    def collect(self) -> tuple[RawNewsItem, ...]:
        detected_at = self._clock()
        if detected_at.tzinfo is None:
            raise ValueError("collector clock must return a timezone-aware datetime")

        date = detected_at.astimezone(SEOUL).strftime("%Y%m%d")
        page_no = 1
        items: list[RawNewsItem] = []

        while True:
            payload = self._fetch_page(date=date, page_no=page_no)
            status = str(payload.get("status", ""))
            message = str(payload.get("message", ""))

            if status == "013":
                return ()
            if status != "000":
                raise OpenDartAPIError(status or "unknown", message or "unknown error")

            rows = payload.get("list", [])
            if not isinstance(rows, list):
                raise ValueError("OpenDART list must be an array")

            items.extend(self._convert_rows(rows, detected_at))

            total_page = _positive_int(payload.get("total_page"), fallback=1)
            if page_no >= total_page:
                break
            page_no += 1

        return tuple(items)

    def _fetch_page(self, *, date: str, page_no: int) -> Mapping[str, Any]:
        return self._fetch_json(
            OPEN_DART_LIST_URL,
            {
                "crtfc_key": self._api_key,
                "bgn_de": date,
                "end_de": date,
                "sort": "date",
                "sort_mth": "asc",
                "page_no": str(page_no),
                "page_count": str(self._page_count),
            },
        )

    @staticmethod
    def _convert_rows(
        rows: list[Any],
        detected_at: datetime,
    ) -> list[RawNewsItem]:
        items: list[RawNewsItem] = []
        for row in rows:
            if not isinstance(row, dict):
                continue

            stock_code = str(row.get("stock_code", "")).strip()
            if len(stock_code) != 6 or not stock_code.isdigit():
                continue

            rcept_no = str(row.get("rcept_no", "")).strip()
            report_name = str(row.get("report_nm", "")).strip()
            corp_name = str(row.get("corp_name", "")).strip()
            if not rcept_no or not report_name:
                continue

            headline = f"{corp_name}: {report_name}" if corp_name else report_name
            items.append(
                RawNewsItem(
                    provider="opendart",
                    provider_item_id=rcept_no,
                    headline=headline,
                    detected_at=detected_at,
                    published_at=None,
                    url=DART_VIEWER_URL.format(rcept_no=rcept_no),
                    symbols=(stock_code,),
                    provider_event_name=report_name,
                )
            )
        return items


def _positive_int(value: Any, *, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback
