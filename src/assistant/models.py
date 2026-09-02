"""Shared domain models for daily report content."""

import hashlib
from dataclasses import asdict, dataclass, field
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



@dataclass
class Favorite:
    """One user-saved content item."""

    item_id: str
    report_date: str = ""
    block_kind: str = ""
    title: str = ""
    url: str = ""
    source: str = ""
    note: str = ""
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""
    user_id: str = "default"


@dataclass
class NewsTerm:
    """One keyword count for one report date."""

    report_date: str
    word: str
    count: int
    rank: int


@dataclass
class GitHubRepo:
    """One repository trend point for one report date."""

    report_date: str
    repo: str
    stars: int
    new_stars: int | None
    rank: int
    appearances: int


def favorite_to_dict(favorite: Favorite) -> dict[str, object]:
    return asdict(favorite)


def news_term_to_dict(term: NewsTerm) -> dict[str, object]:
    return asdict(term)


def github_repo_to_dict(repo: GitHubRepo) -> dict[str, object]:
    return asdict(repo)

@dataclass
class WeatherAlert:
    """One active or historical extreme weather warning for a location."""

    alert_id: str
    location: str
    alert_type: str
    level: str
    title: str = ""
    description: str = ""
    safety_guidance: str = ""
    status: str = "active"
    event_type: str = ""
    published_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    source: str = ""
    source_url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    push_status: str = ""
    push_attempts: int = 0
    pushed_at: datetime | None = None
    first_seen_at: datetime | None = None
    updated_at: datetime | None = None
    last_event_id: int = 0


@dataclass
class WeatherAlertEvent:
    """One state transition in the warning timeline."""

    event_id: int
    alert_id: str
    location: str
    alert_type: str
    level: str
    event_type: str
    title: str = ""
    description: str = ""
    safety_guidance: str = ""
    source: str = ""
    source_url: str = ""
    occurred_at: datetime | None = None
    created_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    push_status: str = ""
    pushed_at: datetime | None = None
    push_channel: str = ""


@dataclass
class WeatherAlertRun:
    """Diagnostic record for one warning source check."""

    checked_at: datetime | None = None
    status: str = "ok"
    source: str = ""
    alert_count: int = 0
    fallback: bool = False
    message: str = ""
    created_at: datetime | None = None
    id: int = 0


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


def _datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def weather_alert_to_dict(alert: WeatherAlert) -> dict[str, Any]:
    return {
        "alert_id": alert.alert_id,
        "location": alert.location,
        "alert_type": alert.alert_type,
        "level": alert.level,
        "title": alert.title,
        "description": alert.description,
        "safety_guidance": alert.safety_guidance,
        "status": alert.status,
        "event_type": alert.event_type,
        "published_at": _encode(alert.published_at),
        "started_at": _encode(alert.started_at),
        "ended_at": _encode(alert.ended_at),
        "source": alert.source,
        "source_url": alert.source_url,
        "raw": alert.raw,
        "push_status": alert.push_status,
        "push_attempts": alert.push_attempts,
        "pushed_at": _encode(alert.pushed_at),
        "first_seen_at": _encode(alert.first_seen_at),
        "updated_at": _encode(alert.updated_at),
        "last_event_id": alert.last_event_id,
    }


def weather_alert_from_dict(data: dict[str, Any]) -> WeatherAlert:
    return WeatherAlert(
        alert_id=data.get("alert_id", ""),
        location=data.get("location", ""),
        alert_type=data.get("alert_type", ""),
        level=data.get("level", ""),
        title=data.get("title", ""),
        description=data.get("description", ""),
        safety_guidance=data.get("safety_guidance", ""),
        status=data.get("status", "active"),
        event_type=data.get("event_type", ""),
        published_at=_datetime_value(data.get("published_at")),
        started_at=_datetime_value(data.get("started_at")),
        ended_at=_datetime_value(data.get("ended_at")),
        source=data.get("source", ""),
        source_url=data.get("source_url", ""),
        raw=data.get("raw", {}),
        push_status=data.get("push_status", ""),
        push_attempts=int(data.get("push_attempts", 0) or 0),
        pushed_at=_datetime_value(data.get("pushed_at")),
        first_seen_at=_datetime_value(data.get("first_seen_at")),
        updated_at=_datetime_value(data.get("updated_at")),
        last_event_id=int(data.get("last_event_id", 0) or 0),
    )


def weather_alert_event_to_dict(event: WeatherAlertEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "alert_id": event.alert_id,
        "location": event.location,
        "alert_type": event.alert_type,
        "level": event.level,
        "event_type": event.event_type,
        "title": event.title,
        "description": event.description,
        "safety_guidance": event.safety_guidance,
        "source": event.source,
        "source_url": event.source_url,
        "occurred_at": _encode(event.occurred_at),
        "created_at": _encode(event.created_at),
        "raw": event.raw,
        "push_status": event.push_status,
        "pushed_at": _encode(event.pushed_at),
        "push_channel": event.push_channel,
    }
