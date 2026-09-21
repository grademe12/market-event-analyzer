from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from market_event_analyzer.providers.opendart import OpenDartAPIError, OpenDartCollector


SEOUL = ZoneInfo("Asia/Seoul")


def main() -> None:
    collector = OpenDartCollector.from_env()
    detected_at = datetime.now(timezone.utc)
    date = detected_at.astimezone(SEOUL).strftime("%Y%m%d")

    payload = collector._fetch_page(date=date, page_no=1)
    status = str(payload.get("status", ""))
    message = str(payload.get("message", ""))

    if status == "013":
        items = ()
    elif status == "000":
        rows = payload.get("list", [])
        if not isinstance(rows, list):
            raise ValueError("OpenDART list must be an array")
        items = tuple(collector._convert_rows(rows, detected_at))
    else:
        raise OpenDartAPIError(status or "unknown", message or "unknown error")

    print("OpenDART live smoke test: PASS")
    print(f"status: {status}")
    print(f"listed disclosures on first page: {len(items)}")
    for item in items[:5]:
        symbol = item.symbols[0] if item.symbols else "-"
        print(f"- {symbol} | {item.headline} | {item.provider_item_id}")


if __name__ == "__main__":
    main()
