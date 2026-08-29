from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from assistant.config import Settings
from assistant.models import ContentBlock, ContentItem, Report
from assistant.report import ReportBuilder, render_report
from assistant.sources.ai import AINewsSource
from assistant.sources.github import GitHubTrendingResult
from assistant.sources.news import NewsSource
from assistant.sources.rss import FeedResult
from assistant.storage import SnapshotStore


class FakeWeatherSource:
    def __init__(self, block: ContentBlock) -> None:
        self.block = block

    def fetch(self, location: str, timezone: str) -> ContentBlock:
        return self.block


class FakeNewsSource:
    def __init__(self, result: FeedResult) -> None:
        self.result = result

    def fetch(self, whitelist, since, limit) -> FeedResult:
        return self.result


class FakeGitHubSource:
    def __init__(self, result: GitHubTrendingResult) -> None:
        self.result = result

    def fetch(self, limit=10) -> GitHubTrendingResult:
        return self.result


class FakeAISource:
    def __init__(self, result: FeedResult) -> None:
        self.result = result

    def fetch(self, whitelist, since, limit) -> FeedResult:
        return self.result


def _item(title: str, url: str, source: str) -> ContentItem:
    return ContentItem(
        title=title,
        url=url,
        source=source,
        published_at=datetime(2026, 8, 28, 1, 0, tzinfo=timezone.utc),
    )


def _settings() -> Settings:
    return Settings(
        location="上海",
        timezone="Asia/Shanghai",
        data_source_whitelist=["weather", "news", "github", "ai"],
        source_whitelist=["people", "openai"],
        push_channels=["wechat_work"],
    )


def test_report_builder_keeps_other_blocks_when_weather_fails() -> None:
    weather = FakeWeatherSource(
        ContentBlock(
            kind="weather",
            title="上海天气",
            status="failed",
            message="天气源不可用",
            sources=["Open-Meteo"],
        )
    )
    news = FakeNewsSource(
        FeedResult(
            items=[_item("新闻一", "https://example.com/news", "人民网")],
            source_statuses={"people": "ok"},
        )
    )
    github = FakeGitHubSource(
        GitHubTrendingResult(
            items=[_item("openai/evals", "https://github.com/openai/evals", "GitHub Trending")],
            mode="official",
        )
    )
    ai = FakeAISource(
        FeedResult(
            items=[_item("AI 动态", "https://example.com/ai", "OpenAI")],
            source_statuses={"openai": "ok"},
        )
    )
    builder = ReportBuilder(
        settings=_settings(),
        weather_source=weather,
        news_source=news,
        github_source=github,
        ai_source=ai,
    )

    report = builder.build(
        now=datetime(2026, 8, 28, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    )

    assert report.title == "上海日报 · 2026-08-28"
    assert [block.kind for block in report.blocks] == [
        "weather",
        "news",
        "github",
        "ai",
    ]
    assert report.blocks[0].status == "failed"
    assert report.degraded is True
    assert report.blocks[1].items[0].url == "https://example.com/news"


def test_snapshot_store_round_trip_and_render_use_same_report(tmp_path: Path) -> None:
    weather = FakeWeatherSource(
        ContentBlock(
            kind="weather",
            title="上海天气",
            status="ok",
            details={"current": {"temperature": 25.0}},
        )
    )
    news = FakeNewsSource(
        FeedResult(
            items=[_item("OpenAI 发布新模型", "https://example.com/openai", "OpenAI")],
            source_statuses={"openai": "ok"},
        )
    )
    github = FakeGitHubSource(GitHubTrendingResult(items=[]))
    ai = FakeAISource(FeedResult(items=[]))
    builder = ReportBuilder(
        settings=_settings(),
        weather_source=weather,
        news_source=news,
        github_source=github,
        ai_source=ai,
    )
    report = builder.build(now=datetime(2026, 8, 28, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")))

    store = SnapshotStore(tmp_path / "report.db")
    report_id = store.save(report)
    loaded = store.load_latest()
    assert report_id == 1
    assert loaded is not None
    assert loaded.title == report.title
    assert loaded.blocks[1].items[0].url == "https://example.com/openai"

    rendered = render_report(loaded)
    assert "上海日报" in rendered
    assert "OpenAI 发布新模型" in rendered