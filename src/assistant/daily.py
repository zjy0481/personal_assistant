"""Daily report generation and push entry point."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from assistant.config import Settings, load_settings
from assistant.models import Report
from assistant.push import PushResult, PushAdapter, create_push_adapter
from assistant.report import ReportBuilder
from assistant.sources.ai import AINewsSource
from assistant.sources.github import GitHubTrendingSource
from assistant.sources.news import NewsSource
from assistant.sources.weather import OpenMeteoWeatherSource
from assistant.storage import SnapshotStore


def create_report_builder(settings: Settings) -> ReportBuilder:
    """Create the real report builder with configured public sources."""

    return ReportBuilder(
        settings=settings,
        weather_source=OpenMeteoWeatherSource(),
        news_source=NewsSource(),
        github_source=GitHubTrendingSource(),
        ai_source=AINewsSource(),
    )


def run_daily(
    settings: Settings | None = None,
    *,
    builder: ReportBuilder | None = None,
    adapter: PushAdapter | None = None,
    store: SnapshotStore | None = None,
    now: datetime | None = None,
) -> PushResult:
    """Generate today's report, save a snapshot, then push it."""

    settings = settings or load_settings()
    builder = builder or create_report_builder(settings)
    adapter = adapter or create_push_adapter(settings)
    store = store or SnapshotStore(Path("data/assistant.db"))
    report = builder.build(
        now=now or datetime.now(ZoneInfo(settings.timezone))
    )
    store.save(report)
    return adapter.send_report(report)
