from collections.abc import Iterable
from pathlib import Path
import sqlite3
from typing import Protocol

from market_event_analyzer.interfaces import NewsCollector
from market_event_analyzer.news import RawNewsItem


class SeenItemStore(Protocol):
    def claim_unseen(
        self,
        items: Iterable[RawNewsItem],
    ) -> tuple[RawNewsItem, ...]: ...


class SQLiteSeenItemStore:
    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_news_items (
                    provider TEXT NOT NULL,
                    provider_item_id TEXT NOT NULL,
                    first_detected_at TEXT NOT NULL,
                    PRIMARY KEY (provider, provider_item_id)
                )
                """
            )

    def claim_unseen(
        self,
        items: Iterable[RawNewsItem],
    ) -> tuple[RawNewsItem, ...]:
        claimed: list[RawNewsItem] = []
        with self._connect() as connection:
            for item in items:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO seen_news_items (
                        provider,
                        provider_item_id,
                        first_detected_at
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        item.provider,
                        item.provider_item_id,
                        item.detected_at.isoformat(),
                    ),
                )
                if cursor.rowcount == 1:
                    claimed.append(item)
        return tuple(claimed)


class DeduplicatingCollector:
    def __init__(
        self,
        collector: NewsCollector,
        store: SeenItemStore,
    ) -> None:
        self._collector = collector
        self._store = store

    def collect(self) -> tuple[RawNewsItem, ...]:
        return self._store.claim_unseen(self._collector.collect())
