from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from assistant.config import Settings
from assistant.daily import run_daily
from assistant.models import ContentBlock, Report
from assistant.push import PushResult
from assistant.storage import SnapshotStore


class _FakeBuilder:
    def __init__(self, report: Report) -> None:
        self.report = report

    def build(self, now: datetime | None = None) -> Report:
        return self.report


class _FakeAdapter:
    def __init__(self) -> None:
        self.report: Report | None = None

    def send_report(self, report: Report) -> PushResult:
        self.report = report
        return PushResult(
            success=True,
            mode="pushplus",
            channel="pushplus",
            message="ok",
        )


def _settings() -> Settings:
    return Settings(
        location="上海",
        timezone="Asia/Shanghai",
        push_channels=["pushplus"],
        pushplus_token="pushplus-token",
        push_mock=False,
    )


def _report() -> Report:
    return Report(
        title="上海日报 · 2026-08-29",
        generated_at=datetime(2026, 8, 29, 8, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        location="上海",
        timezone="Asia/Shanghai",
        blocks=[
            ContentBlock(
                kind="news",
                title="时事新闻",
                status="ok",
            )
        ],
    )


def test_run_daily_builds_saves_snapshot_and_pushes(
    tmp_path: Path,
) -> None:
    builder = _FakeBuilder(_report())
    adapter = _FakeAdapter()
    store = SnapshotStore(tmp_path / "daily.db")

    result = run_daily(
        _settings(),
        builder=builder,
        adapter=adapter,
        store=store,
        now=datetime(2026, 8, 29, 8, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert result.success is True
    assert adapter.report is not None
    assert adapter.report.title == "上海日报 · 2026-08-29"
    assert store.load_latest() is not None
    assert store.load_latest().title == "上海日报 · 2026-08-29"
