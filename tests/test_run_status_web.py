from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from assistant.app import create_app
from assistant.config import Settings
from assistant.models import ContentBlock, Report
from assistant.storage import RunStatus, SnapshotStore


def _report() -> Report:
    return Report(
        title="上海日报 · 2026-08-29",
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
            ContentBlock(kind="news", title="时事新闻", status="ok"),
        ],
    )


def test_home_page_shows_latest_daily_run_status(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(tmp_path / "web.db")
    store.save(_report())
    store.save_run_status(
        RunStatus(
            report_date="2026-08-29",
            status="failed",
            message="推送失败",
        )
    )
    app = create_app(
        Settings(location="上海", timezone="Asia/Shanghai"),
        store=store,
    )

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "最近一次运行" in response.text
    assert "推送失败" in response.text
