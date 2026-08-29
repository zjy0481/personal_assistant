from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from assistant.models import ContentBlock, Report
from assistant.storage import (
    SnapshotAlreadyExistsError,
    SnapshotStore,
    RunStatus,
)


def _report(title: str = "上海日报 · 2026-08-29") -> Report:
    return Report(
        title=title,
        generated_at=datetime(
            2026,
            8,
            29,
            8,
            30,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ),
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


def test_snapshot_duplicate_date_is_blocked_without_force(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "report.db")

    store.save(_report())

    assert store.has_report_for_date("2026-08-29") is True
    with pytest.raises(SnapshotAlreadyExistsError):
        store.save(_report())


def test_force_replaces_same_day_snapshot(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "report.db")
    store.save(_report())
    next_report = _report(title="上海日报 · 2026-08-29（重新生成）")

    new_id = store.save(next_report, force=True)

    assert new_id == 2
    assert store.load_latest() is not None
    assert store.load_latest().title == "上海日报 · 2026-08-29（重新生成）"
    assert store.load_latest().generated_at == next_report.generated_at


def test_run_status_is_replaced_per_day(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "status.db")
    first = RunStatus(
        report_date="2026-08-29",
        status="ok",
        channel="pushplus",
        short_code="abc",
        message="成功",
    )
    second = RunStatus(
        report_date="2026-08-29",
        status="failed",
        message="推送失败",
    )

    store.save_run_status(first)
    store.save_run_status(second)

    latest = store.load_latest_run_status()
    assert latest is not None
    assert latest.status == "failed"
    assert latest.message == "推送失败"
