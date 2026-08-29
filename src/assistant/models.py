"""Shared domain models for daily report content."""

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class ContentItem:
    """One traceable item inside a content block."""

    title: str
    url: str
    source: str
    published_at: datetime | None = None
    summary: str = ""
    language: str = ""
    category: str = ""
    stars: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    item_id: str = ""
    llm_summary: str = ""
    summary_status: str = ""
    summary_model: str = ""

    @property
    def content_key(self) -> str:
        return (self.url or self.title).strip().lower()

    @property
    def stable_id(self) -> str:
        if self.item_id.strip():
            return self.item_id.strip()
        return compute_item_id(
            title=self.title,
            url=self.url,
            source=self.source,
        )


def compute_item_id(title: str, url: str, source: str) -> str:
    """Return a deterministic 16-character item id.

    URL is preferred because it identifies the same source across daily
    snapshots. Without a URL, title plus source is used to keep old records
    stable and reproducible.
    """
    seed = (url or "").strip().lower()
    if not seed:
        seed = f"{title}|{source}".strip().lower()
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


@dataclass
class ContentBlock:
    """A standardized section produced by one or more data sources."""

    kind: str
    title: str
    status: str = "ok"
    items: list[ContentItem] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    message: str | None = None


@dataclass
class Report:
    """The canonical daily report used by push and web surfaces."""

    title: str
    generated_at: datetime
    location: str
    timezone: str
    blocks: list[ContentBlock]
    degraded: bool = False


def _encode(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    return value


def content_item_to_dict(item: ContentItem) -> dict[str, Any]:
    return {
        "title": item.title,
        "url": item.url,
        "source": item.source,
        "published_at": _encode(item.published_at),
        "summary": item.summary,
        "language": item.language,
        "category": item.category,
        "stars": item.stars,
        "metadata": item.metadata,
        "item_id": item.stable_id,
        "llm_summary": item.llm_summary,
        "summary_status": item.summary_status,
        "summary_model": item.summary_model,
    }


def content_block_to_dict(block: ContentBlock) -> dict[str, Any]:
    return {
        "kind": block.kind,
        "title": block.title,
        "status": block.status,
        "items": [content_item_to_dict(item) for item in block.items],
        "details": _encode(block.details),
        "sources": list(block.sources),
        "message": block.message,
    }


def report_to_dict(report: Report) -> dict[str, Any]:
    return {
        "title": report.title,
        "generated_at": _encode(report.generated_at),
        "location": report.location,
        "timezone": report.timezone,
        "blocks": [content_block_to_dict(block) for block in report.blocks],
        "degraded": report.degraded,
    }


def content_item_from_dict(data: dict[str, Any]) -> ContentItem:
    published_at = data.get("published_at")
    if isinstance(published_at, str):
        published_at = datetime.fromisoformat(published_at)
    return ContentItem(
        title=data["title"],
        url=data["url"],
        source=data["source"],
        published_at=published_at,
        summary=data.get("summary", ""),
        language=data.get("language", ""),
        category=data.get("category", ""),
        stars=data.get("stars"),
        metadata=data.get("metadata", {}),
        item_id=data.get("item_id", ""),
        llm_summary=data.get("llm_summary", ""),
        summary_status=data.get("summary_status", ""),
        summary_model=data.get("summary_model", ""),
    )


def content_block_from_dict(data: dict[str, Any]) -> ContentBlock:
    return ContentBlock(
        kind=data["kind"],
        title=data["title"],
        status=data.get("status", "ok"),
        items=[
            content_item_from_dict(item) for item in data.get("items", [])
        ],
        details=data.get("details", {}),
        sources=list(data.get("sources", [])),
        message=data.get("message"),
    )


def report_from_dict(data: dict[str, Any]) -> Report:
    generated_at = datetime.fromisoformat(data["generated_at"])
    return Report(
        title=data["title"],
        generated_at=generated_at,
        location=data["location"],
        timezone=data["timezone"],
        blocks=[content_block_from_dict(item) for item in data["blocks"]],
        degraded=bool(data.get("degraded", False)),
    )