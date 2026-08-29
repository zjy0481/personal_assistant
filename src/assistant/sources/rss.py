"""Generic RSS/Atom feed parsing shared by news and AI sources."""

import html
import re
import xml.etree.ElementTree as ET
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from assistant.models import ContentItem

_TAG_RE = re.compile(r"<[^>]+>")
_DEFAULT_MIN = datetime.min.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Feed:
    """One configured RSS/Atom feed."""

    key: str
    name: str
    url: str
    language: str = ""
    category: str = ""


@dataclass
class FeedResult:
    """Items plus per-source availability."""

    items: list[ContentItem] = field(default_factory=list)
    source_statuses: dict[str, str] = field(default_factory=dict)


def _strip_html(value: str) -> str:
    return html.unescape(_TAG_RE.sub("", value or "")).strip()


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


class RssSource:
    """Fetch a set of feeds and return a normalized, deduplicated result."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            timeout=10.0,
            follow_redirects=True,
        )

    def fetch(
        self,
        feeds: list[Feed],
        whitelist: Collection[str],
        since: datetime | None = None,
        limit: int = 10,
    ) -> FeedResult:
        result = FeedResult()
        seen: set[str] = set()
        allowed = set(whitelist)

        for feed in feeds:
            if feed.key not in allowed:
                continue
            try:
                items = self._fetch_feed(feed)
                result.source_statuses[feed.key] = "ok"
            except Exception as exc:
                result.source_statuses[feed.key] = f"failed: {exc}"
                continue

            if since is not None:
                items = [
                    item
                    for item in items
                    if item.published_at is not None
                    and item.published_at >= since
                ]

            for item in items:
                result.items.append(item)

        result.items.sort(
            key=lambda item: item.published_at or _DEFAULT_MIN,
            reverse=True,
        )
        unique: list[ContentItem] = []
        for item in result.items:
            key = item.content_key
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)

        result.items = unique[: max(limit, 0)]
        return result

    def _fetch_feed(self, feed: Feed) -> list[ContentItem]:
        response = self.client.get(
            feed.url,
            headers={
                "User-Agent": "personal-assistant/0.1 (+https://github.com/zjy0481/personal_assistant)"
            },
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        items: list[ContentItem] = []

        for element in root.iter():
            if _local_name(element.tag) != "item":
                continue
            item_data: dict[str, str] = {}
            for child in element:
                item_data[_local_name(child.tag)] = child.text or ""

            title = _strip_html(item_data.get("title", ""))
            url = _strip_html(item_data.get("link", ""))
            if not title or not url:
                continue

            items.append(
                ContentItem(
                    title=title,
                    url=url,
                    source=feed.name,
                    published_at=_parse_datetime(item_data.get("pubdate", "")),
                    summary=_strip_html(item_data.get("description", "")),
                    language=feed.language,
                    category=feed.category,
                    metadata={"feed_key": feed.key, "feed_url": feed.url},
                )
            )

        return items