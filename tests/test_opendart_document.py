from datetime import datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo

import pytest

from market_event_analyzer.news import RawNewsItem
from market_event_analyzer.providers.opendart import OpenDartAPIError
from market_event_analyzer.providers.opendart_document import (
    OPEN_DART_DOCUMENT_URL,
    OpenDartDisclosureEnricher,
    OpenDartDocumentError,
)


SEOUL = ZoneInfo("Asia/Seoul")
RCEPT_NO = "20260922000123"


def raw_item() -> RawNewsItem:
    return RawNewsItem(
        provider="opendart",
        provider_item_id=RCEPT_NO,
        headline="테스트회사: 단일판매ㆍ공급계약체결",
        detected_at=datetime(2026, 9, 22, 18, 0, tzinfo=SEOUL),
        published_at=None,
        url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={RCEPT_NO}",
        symbols=("005930",),
        provider_event_name="단일판매ㆍ공급계약체결",
    )


def document_zip(files: dict[str, str], *, encoding: str = "utf-8") -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content.encode(encoding))
    return output.getvalue()


def test_enricher_fetches_receipt_document_and_preserves_metadata() -> None:
    calls = []

    def fetch_bytes(url, params):
        calls.append((url, dict(params)))
        return document_zip(
            {
                RCEPT_NO + ".xml": """
                    <DOCUMENT>
                      <P>단일판매ㆍ공급계약 체결</P>
                      <TABLE>
                        <TR><TH>계약금액</TH><TD>12,345,678,000원</TD></TR>
                        <TR><TH>최근 매출액 대비</TH><TD>18.4%</TD></TR>
                      </TABLE>
                    </DOCUMENT>
                """,
                RCEPT_NO + "_00001.xml": "<DOCUMENT><P>첨부 문서</P></DOCUMENT>",
            }
        )

    original = raw_item()
    enriched = OpenDartDisclosureEnricher(
        "test-key",
        fetch_bytes=fetch_bytes,
    ).enrich(original)

    assert enriched.provider == original.provider
    assert enriched.provider_item_id == original.provider_item_id
    assert enriched.headline == original.headline
    assert enriched.detected_at == original.detected_at
    assert enriched.published_at == original.published_at
    assert enriched.url == original.url
    assert enriched.symbols == original.symbols
    assert enriched.provider_event_name == original.provider_event_name
    assert "단일판매ㆍ공급계약 체결" in enriched.body
    assert "계약금액 | 12,345,678,000원" in enriched.body
    assert "최근 매출액 대비 | 18.4%" in enriched.body
    assert "첨부 문서" not in enriched.body

    assert calls == [
        (
            OPEN_DART_DOCUMENT_URL,
            {
                "crtfc_key": "test-key",
                "rcept_no": RCEPT_NO,
            },
        )
    ]


def test_single_xml_fallback_is_supported_when_exact_receipt_name_is_absent() -> None:
    payload = document_zip(
        {"document.xml": "<DOCUMENT><P>본문 텍스트</P></DOCUMENT>"}
    )

    enriched = OpenDartDisclosureEnricher(
        "test-key",
        fetch_bytes=lambda *_: payload,
    ).enrich(raw_item())

    assert enriched.body == "본문 텍스트"


def test_cp949_document_is_decoded() -> None:
    payload = document_zip(
        {RCEPT_NO + ".xml": "<DOCUMENT><P>계약 체결 완료</P></DOCUMENT>"},
        encoding="cp949",
    )

    enriched = OpenDartDisclosureEnricher(
        "test-key",
        fetch_bytes=lambda *_: payload,
    ).enrich(raw_item())

    assert enriched.body == "계약 체결 완료"


def test_body_length_limit_is_deterministic() -> None:
    payload = document_zip(
        {RCEPT_NO + ".xml": "<DOCUMENT><P>abcdefghij</P></DOCUMENT>"}
    )

    enriched = OpenDartDisclosureEnricher(
        "test-key",
        fetch_bytes=lambda *_: payload,
        max_body_chars=6,
    ).enrich(raw_item())

    assert enriched.body == "abcdef"


def test_open_dart_api_error_payload_is_raised() -> None:
    payload = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<result><status>020</status><message>요청 제한을 초과하였습니다.</message></result>"
    ).encode()

    with pytest.raises(OpenDartAPIError) as exc_info:
        OpenDartDisclosureEnricher(
            "test-key",
            fetch_bytes=lambda *_: payload,
        ).enrich(raw_item())

    assert exc_info.value.status == "020"
    assert "요청 제한" in exc_info.value.message


def test_multiple_xml_files_without_main_receipt_document_are_rejected() -> None:
    payload = document_zip(
        {
            "attachment-a.xml": "<DOCUMENT><P>A</P></DOCUMENT>",
            "attachment-b.xml": "<DOCUMENT><P>B</P></DOCUMENT>",
        }
    )

    with pytest.raises(OpenDartDocumentError, match="multiple XML"):
        OpenDartDisclosureEnricher(
            "test-key",
            fetch_bytes=lambda *_: payload,
        ).enrich(raw_item())


def test_empty_document_is_rejected() -> None:
    payload = document_zip(
        {RCEPT_NO + ".xml": "<DOCUMENT><TABLE><TR><TD>   </TD></TR></TABLE></DOCUMENT>"}
    )

    with pytest.raises(OpenDartDocumentError, match="no readable text"):
        OpenDartDisclosureEnricher(
            "test-key",
            fetch_bytes=lambda *_: payload,
        ).enrich(raw_item())


def test_non_opendart_item_is_rejected_without_fetching() -> None:
    called = False

    def fetch_bytes(*_):
        nonlocal called
        called = True
        return b""

    item = RawNewsItem(
        provider="other",
        provider_item_id="provider-1",
        headline="headline",
        detected_at=datetime(2026, 9, 22, 18, 0, tzinfo=SEOUL),
    )

    with pytest.raises(ValueError, match="provider='opendart'"):
        OpenDartDisclosureEnricher(
            "test-key",
            fetch_bytes=fetch_bytes,
        ).enrich(item)

    assert called is False
