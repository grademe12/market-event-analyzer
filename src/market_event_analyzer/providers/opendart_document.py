from collections.abc import Callable, Mapping
from dataclasses import replace
from html.parser import HTMLParser
from io import BytesIO
import re
from typing import Final
from urllib.parse import urlencode
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile

from market_event_analyzer.news import RawNewsItem
from market_event_analyzer.providers.opendart import OpenDartAPIError


OPEN_DART_DOCUMENT_URL: Final = "https://opendart.fss.or.kr/api/document.xml"
DEFAULT_MAX_BODY_CHARS: Final = 30_000
MAX_ARCHIVE_BYTES: Final = 25 * 1024 * 1024

BinaryFetcher = Callable[[str, Mapping[str, str]], bytes]


class OpenDartDocumentError(RuntimeError):
    pass


def _fetch_bytes(url: str, params: Mapping[str, str]) -> bytes:
    request_url = f"{url}?{urlencode(params)}"
    with urlopen(request_url, timeout=20) as response:
        payload = response.read(MAX_ARCHIVE_BYTES + 1)
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise OpenDartDocumentError("OpenDART document archive exceeds size limit")
    return payload


class OpenDartDisclosureEnricher:
    """Fetch and deterministically convert one OpenDART filing into readable text."""

    def __init__(
        self,
        api_key: str,
        *,
        fetch_bytes: BinaryFetcher = _fetch_bytes,
        max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key must not be blank")
        if max_body_chars < 1:
            raise ValueError("max_body_chars must be positive")
        self._api_key = api_key
        self._fetch_bytes = fetch_bytes
        self._max_body_chars = max_body_chars

    def enrich(self, item: RawNewsItem) -> RawNewsItem:
        if item.provider != "opendart":
            raise ValueError("OpenDartDisclosureEnricher requires provider='opendart'")
        rcept_no = item.provider_item_id.strip()
        if len(rcept_no) != 14 or not rcept_no.isdigit():
            raise ValueError("OpenDART provider_item_id must be a 14-digit receipt number")

        payload = self._fetch_bytes(
            OPEN_DART_DOCUMENT_URL,
            {
                "crtfc_key": self._api_key,
                "rcept_no": rcept_no,
            },
        )
        document = _read_main_document(payload, rcept_no)
        body = _extract_text(document)
        if not body:
            raise OpenDartDocumentError("OpenDART main document contains no readable text")
        return replace(item, body=body[: self._max_body_chars].rstrip())


def _read_main_document(payload: bytes, rcept_no: str) -> str:
    try:
        archive = ZipFile(BytesIO(payload))
    except BadZipFile as exc:
        api_error = _parse_api_error(payload)
        if api_error is not None:
            raise api_error
        raise OpenDartDocumentError("OpenDART document response is not a valid ZIP archive") from exc

    with archive:
        candidates = [
            info
            for info in archive.infolist()
            if not info.is_dir() and info.filename.lower().endswith(".xml")
        ]
        if not candidates:
            raise OpenDartDocumentError("OpenDART document archive contains no XML document")

        exact_name = f"{rcept_no}.xml"
        exact = [
            info
            for info in candidates
            if info.filename.rsplit("/", 1)[-1] == exact_name
        ]
        if exact:
            selected = exact[0]
        elif len(candidates) == 1:
            selected = candidates[0]
        else:
            raise OpenDartDocumentError(
                "OpenDART document archive contains multiple XML files but no main receipt document"
            )

        return _decode_document(archive.read(selected))


def _decode_document(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise OpenDartDocumentError("OpenDART main document encoding is unsupported")


def _parse_api_error(payload: bytes) -> OpenDartAPIError | None:
    text = payload.decode("utf-8", errors="replace")
    status = _xml_field(text, "status")
    if not status:
        return None
    message = _xml_field(text, "message") or "unknown error"
    return OpenDartAPIError(status, message)


def _xml_field(text: str, field: str) -> str:
    match = re.search(
        rf"<{field}>\s*(.*?)\s*</{field}>",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


class _DartTextParser(HTMLParser):
    _LINE_TAGS = {
        "body",
        "div",
        "li",
        "p",
        "section",
        "table",
        "tbody",
        "thead",
        "title",
        "tr",
    }
    _CELL_TAGS = {"td", "th"}
    _SKIP_TAGS = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "br" or tag in self._LINE_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in self._CELL_TAGS:
            self.parts.append("\t")
        elif tag in self._LINE_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def _extract_text(document: str) -> str:
    parser = _DartTextParser()
    try:
        parser.feed(document)
        parser.close()
    except Exception as exc:
        raise OpenDartDocumentError("OpenDART main document could not be parsed") from exc

    lines: list[str] = []
    for raw_line in "".join(parser.parts).replace("\r", "\n").splitlines():
        line = raw_line.replace("\t", " | ")
        line = re.sub(r"[ \f\v]+", " ", line)
        line = re.sub(r"\s*\|\s*", " | ", line)
        line = line.strip(" |")
        if line:
            lines.append(line)
    return "\n".join(lines)
