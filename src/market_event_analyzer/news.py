from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RawNewsItem:
    provider: str
    provider_item_id: str
    headline: str
    detected_at: datetime
    published_at: datetime | None = None
    body: str = ""
    url: str = ""
    symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider must not be blank")
        if not self.provider_item_id.strip():
            raise ValueError("provider_item_id must not be blank")
        if not self.headline.strip():
            raise ValueError("headline must not be blank")
        if self.detected_at.tzinfo is None:
            raise ValueError("detected_at must be timezone-aware")
        if self.published_at is not None:
            if self.published_at.tzinfo is None:
                raise ValueError("published_at must be timezone-aware when provided")
            if self.detected_at < self.published_at:
                raise ValueError("detected_at must not be before published_at")
        if any(not symbol.strip() for symbol in self.symbols):
            raise ValueError("symbols must not contain blank values")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("symbols must not contain duplicates")
