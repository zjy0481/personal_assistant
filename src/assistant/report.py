"""Deterministic daily report assembly and template rendering."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from assistant.config import Settings
from assistant.models import ContentBlock, ContentItem, Report, report_to_dict

TEMPLATE_DIR = Path(__file__).parent / "templates"
_DEFAULT_MIN = datetime.min.replace(tzinfo=ZoneInfo("UTC"))


class ReportBuilder:
    """Collect configured data sources into one canonical report."""

    def __init__(
        self,
        settings: Settings,
        weather_source: Any,
        news_source: Any,
        github_source: Any,
        ai_source: Any,
    ) -> None:
        self.settings = settings
        self.weather_source = weather_source
        self.news_source = news_source
        self.github_source = github_source
        self.ai_source = ai_source

    def build(self, now: datetime | None = None) -> Report:
        now = now or datetime.now(ZoneInfo(self.settings.timezone))
        since = now - timedelta(days=1)
        enabled = set(self.settings.data_source_whitelist)
        blocks: list[ContentBlock] = []

        if "weather" in enabled:
            blocks.append(self._weather_block())
        if "news" in enabled:
            blocks.append(self._news_block(since=since))
        if "github" in enabled:
            blocks.append(self._github_block())
        if "ai" in enabled:
            blocks.append(self._ai_block(since=since))

        title = f"{self.settings.location}日报 · {now:%Y-%m-%d}"
        return Report(
            title=title,
            generated_at=now,
            location=self.settings.location,
            timezone=self.settings.timezone,
            blocks=blocks,
            degraded=any(block.status != "ok" for block in blocks),
        )

    def _weather_block(self) -> ContentBlock:
        try:
            return self.weather_source.fetch(
                self.settings.location,
                self.settings.timezone,
            )
        except Exception as exc:
            return ContentBlock(
                kind="weather",
                title=f"{self.settings.location}天气",
                status="failed",
                sources=["Open-Meteo"],
                message=f"天气数据源不可用: {exc}",
            )

    def _news_block(self, since: datetime) -> ContentBlock:
        try:
            result = self.news_source.fetch(
                whitelist=self.settings.source_whitelist,
                since=since,
                limit=10,
            )
        except Exception as exc:
            return self._failed_block("news", "时事新闻", "新闻数据源", exc)
        return self._feed_block(
            kind="news",
            title="时事新闻",
            result=result,
            limit=10,
        )

    def _github_block(self) -> ContentBlock:
        try:
            result = self.github_source.fetch(limit=10)
        except Exception as exc:
            return self._failed_block(
                "github",
                "GitHub 热门",
                "GitHub Trending",
                exc,
            )
        return ContentBlock(
            kind="github",
            title="GitHub 热门",
            status="degraded" if result.degraded else "ok",
            items=_deduplicate_and_limit(result.items, 10),
            sources=[]
            if result.mode == "official"
            else ["GitHub Search API"],
            message=result.message or None,
        )

    def _ai_block(self, since: datetime) -> ContentBlock:
        try:
            result = self.ai_source.fetch(
                whitelist=self.settings.source_whitelist,
                since=since,
                limit=8,
            )
        except Exception as exc:
            return self._failed_block("ai", "AI 领域要事", "AI 数据源", exc)
        return self._feed_block(
            kind="ai",
            title="AI 领域要事",
            result=result,
            limit=8,
        )

    def _feed_block(
        self,
        kind: str,
        title: str,
        result: Any,
        limit: int,
    ) -> ContentBlock:
        failures = {
            key: value
            for key, value in result.source_statuses.items()
            if value != "ok"
        }
        status = "degraded" if failures else "ok"
        return ContentBlock(
            kind=kind,
            title=title,
            status=status,
            items=_deduplicate_and_limit(result.items, limit),
            sources=list(result.source_statuses),
            message="; ".join(
                f"{key}: {value}" for key, value in failures.items()
            )
            or None,
        )

    def _failed_block(
        self,
        kind: str,
        title: str,
        source: str,
        exc: Exception,
    ) -> ContentBlock:
        return ContentBlock(
            kind=kind,
            title=title,
            status="failed",
            sources=[source],
            message=f"{source}不可用: {exc}",
        )


def _deduplicate_and_limit(
    items: list[ContentItem],
    limit: int,
) -> list[ContentItem]:
    seen: set[str] = set()
    result: list[ContentItem] = []
    for item in sorted(
        items,
        key=lambda value: value.published_at or _DEFAULT_MIN,
        reverse=True,
    ):
        if item.content_key in seen:
            continue
        seen.add(item.content_key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def render_report(report: Report) -> str:
    """Render the canonical report through the shared Jinja template."""

    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
    )
    template = environment.get_template("report.html")
    return template.render(report=report_to_dict(report))