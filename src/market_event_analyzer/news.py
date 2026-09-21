from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RawNewsItem:
    provider: str
    provider_item_id: str
    headline: str
    published_at: datetime
    detected_at: datetime
    body: str = ""
    url: str = ""

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider must not be blank")
        if not self.provider_item_id.strip():
            raise ValueError("provider_item_id must not be blank")
        if not self.headline.strip():
            raise ValueError("headline must not be blank")
        if self.published_at.tzinfo is None or self.detected_at.tzinfo is None:
            raise ValueError("news timestamps must be timezone-aware")
        if self.detected_at < self.published_at:
            raise ValueError("detected_at must not be before published_at")
