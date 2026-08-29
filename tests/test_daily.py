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
        self.calls = 0

    def build(self, now: datetime | None = None) -> Report:
        self.calls += 1
        return self.report


class _FlakyBuilder:
    def __init__(self, report: Report) -> None:
        self.report = report
        self.calls = 0

    def build(self, now: datetime | None = None) -> Report:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary failure")
        return self.report


class _FakeAdapter:
    def __init__(self) -> None:
        self.report: Report | None = None
        self.calls = 0

    def send_report(self, report: Report) -> PushResult:
        self.calls += 1
        self.report = report
        return PushResult(
            success=True,
            mode="pushplus",
            channel="pushplus",
            message="ok",
        )


class _RetryAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def send_report(self, report: Report) -> PushResult:
        self.calls += 1
        if self.calls == 1:
            return PushResult(
                success=False,
                mode="failed",
                channel="pushplus",
                message="network failure",
            )
        return PushResult(
            success=True,
            mode="pushplus",
            channel="pushplus",
            message="ok",
        )


class _TerminalFailureAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def send_report(self, report: Report) -> PushResult:
        self.calls += 1
        return PushResult(
            success=False,
            mode="failed",
            channel="pushplus",
            errcode=903,
            message="token invalid",
            retryable=False,
        )


def _settings() -> Settings:
    return Settings(
        location="上海",
        timezone="Asia/Shanghai",
        push_channels=["pushplus"],
        pushplus_token="pushplus-token",
        push_mock=False,
        daily_retry_max=3,
        daily_retry_interval_seconds=30,
    )


def _report(title: str = "上海日报 · 2026-08-29") -> Report:
    return Report(
        title=title,
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


def _now() -> datetime:
    return datetime(2026, 8, 29, 8, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


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
        now=_now(),
    )

    assert result.success is True
    assert adapter.report is not None
    assert adapter.report.title == "上海日报 · 2026-08-29"
    assert store.load_latest() is not None
    assert store.load_latest().title == "上海日报 · 2026-08-29"
    assert store.load_latest_run_status() is not None
    assert store.load_latest_run_status().status == "ok"


def test_run_daily_skips_existing_same_day_without_force(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "daily.db")
    store.save(_report())
    builder = _FakeBuilder(_report())
    adapter = _FakeAdapter()

    result = run_daily(
        _settings(),
        builder=builder,
        adapter=adapter,
        store=store,
        now=_now(),
    )

    assert result.success is True
    assert result.mode == "skipped"
    assert builder.calls == 0
    assert adapter.calls == 0
    assert store.load_latest_run_status() is not None
    assert store.load_latest_run_status().status == "skipped"


def test_run_daily_force_replaces_same_day_snapshot(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "daily.db")
    store.save(_report())
    builder = _FakeBuilder(_report(title="上海日报 · 2026-08-29（重新生成）"))
    adapter = _FakeAdapter()

    result = run_daily(
        _settings(),
        builder=builder,
        adapter=adapter,
        store=store,
        now=_now(),
        force=True,
    )

    assert result.success is True
    assert builder.calls == 1
    assert adapter.calls == 1
    assert store.load_latest() is not None
    assert store.load_latest().title == "上海日报 · 2026-08-29（重新生成）"


def test_run_daily_retries_generation_failure(tmp_path: Path) -> None:
    builder = _FlakyBuilder(_report())
    adapter = _FakeAdapter()
    store = SnapshotStore(tmp_path / "daily.db")

    result = run_daily(
        _settings(),
        builder=builder,
        adapter=adapter,
        store=store,
        now=_now(),
        retry_max=2,
        retry_interval_seconds=0,
    )

    assert result.success is True
    assert builder.calls == 2


def test_run_daily_retries_transport_push_failure(tmp_path: Path) -> None:
    adapter = _RetryAdapter()
    store = SnapshotStore(tmp_path / "daily.db")

    result = run_daily(
        _settings(),
        builder=_FakeBuilder(_report()),
        adapter=adapter,
        store=store,
        now=_now(),
        retry_max=2,
        retry_interval_seconds=0,
    )

    assert result.success is True
    assert adapter.calls == 2
    assert store.load_latest_run_status() is not None
    assert store.load_latest_run_status().status == "ok"


def test_run_daily_does_not_retry_terminal_push_error(tmp_path: Path) -> None:
    adapter = _TerminalFailureAdapter()
    store = SnapshotStore(tmp_path / "daily.db")

    result = run_daily(
        _settings(),
        builder=_FakeBuilder(_report()),
        adapter=adapter,
        store=store,
        now=_now(),
        retry_max=2,
        retry_interval_seconds=0,
    )

    assert result.success is False
    assert adapter.calls == 1
    assert store.load_latest_run_status() is not None
    assert store.load_latest_run_status().status == "failed"