"""Daily report generation with retry, deduplication and run status."""

import logging
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from assistant.config import Settings, load_settings
from assistant.llm import create_llm_service
from assistant.models import Report
from assistant.push import PushAdapter, PushResult, create_push_adapter
from assistant.report import ReportBuilder
from assistant.sources.ai import AINewsSource
from assistant.sources.github import GitHubTrendingSource
from assistant.sources.news import NewsSource
from assistant.sources.weather import OpenMeteoWeatherSource
from assistant.storage import RunStatus, SnapshotAlreadyExistsError, SnapshotStore

logger = logging.getLogger(__name__)


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
    force: bool = False,
    retry_max: int | None = None,
    retry_interval_seconds: int | None = None,
) -> PushResult:
    """Generate today's report, save a snapshot, then push it.

    Same-day snapshots are skipped by default; ``force`` replaces the
    existing snapshot. Retries cover generation and transport-level push
    failures, but not API rejections that are marked non-retryable.
    """

    settings = settings or load_settings()
    now = now or datetime.now(ZoneInfo(settings.timezone))
    report_date = now.date().isoformat()
    builder = builder or create_report_builder(settings)
    adapter = adapter or create_push_adapter(settings)
    store = store or SnapshotStore(Path("data/assistant.db"))
    max_attempts = max(1, retry_max or settings.daily_retry_max)
    interval = (
        retry_interval_seconds
        if retry_interval_seconds is not None
        else settings.daily_retry_interval_seconds
    )

    if not force and store.has_report_for_date(report_date):
        message = "今日日报已生成，跳过重复推送"
        store.save_run_status(
            RunStatus(
                report_date=report_date,
                status="skipped",
                message=message,
            )
        )
        return PushResult(
            success=True,
            mode="skipped",
            message=message,
        )

    report = _build_with_retry(
        builder,
        now=now,
        max_attempts=max_attempts,
        interval=interval,
    )
    if report is None:
        message = f"日报生成失败，已重试 {max_attempts} 次"
        store.save_run_status(
            RunStatus(
                report_date=report_date,
                status="failed",
                message=message,
            )
        )
        return PushResult(
            success=False,
            mode="failed",
            message=message,
        )

    try:
        store.save(report, force=force)
    except SnapshotAlreadyExistsError:
        message = "今日日报已生成，跳过重复推送"
        store.save_run_status(
            RunStatus(
                report_date=report_date,
                status="skipped",
                message=message,
            )
        )
        return PushResult(
            success=True,
            mode="skipped",
            message=message,
        )
    except Exception as exc:
        message = f"日报快照保存失败: {exc}"
        store.save_run_status(
            RunStatus(
                report_date=report_date,
                status="failed",
                message=message,
            )
        )
        return PushResult(
            success=False,
            mode="failed",
            message=message,
        )

    result = _push_with_retry(
        adapter,
        report=report,
        max_attempts=max_attempts,
        interval=interval,
    )
    store.save_run_status(
        RunStatus(
            report_date=report_date,
            status="ok" if result.success else "failed",
            channel=result.channel,
            short_code=result.short_code,
            message=result.message,
        )
    )
    return result


def _build_with_retry(
    builder: object,
    *,
    now: datetime,
    max_attempts: int,
    interval: int,
) -> Report | None:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return builder.build(now=now)
        except Exception as exc:
            last_error = exc
            logger.warning(
                "日报生成第 %s/%s 次失败：%s",
                attempt,
                max_attempts,
                exc,
            )
            if attempt < max_attempts:
                time.sleep(interval)
    logger.error("日报生成最终失败：%s", last_error)
    return None


def _push_with_retry(
    adapter: PushAdapter,
    *,
    report: Report,
    max_attempts: int,
    interval: int,
) -> PushResult:
    last_result = PushResult(
        success=False,
        mode="failed",
        message="推送失败",
    )
    for attempt in range(1, max_attempts + 1):
        try:
            result = adapter.send_report(report)
        except Exception as exc:
            result = PushResult(
                success=False,
                mode="failed",
                message=f"推送渠道异常: {exc}",
            )
        if result.success or not result.retryable:
            return result
        last_result = result
        logger.warning(
            "日报推送第 %s/%s 次失败：%s",
            attempt,
            max_attempts,
            result.message,
        )
        if attempt < max_attempts:
            time.sleep(interval)
    return last_result