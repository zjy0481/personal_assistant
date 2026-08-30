from datetime import datetime
from zoneinfo import ZoneInfo
import sys

from assistant import __main__ as cli
from assistant.push import PushResult


def test_daily_command_forwards_force_flag(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_daily(**kwargs):
        captured.update(kwargs)
        return PushResult(success=True, mode="mock", message="ok")

    monkeypatch.setattr("assistant.daily.run_daily", fake_run_daily)
    monkeypatch.setattr(sys, "argv", ["assistant", "daily", "--force"])

    assert cli.main() == 0
    assert captured["force"] is True


def test_alert_once_command_runs_single_check(monkeypatch) -> None:
    from assistant.weather_alert_service import AlertMonitorResult

    captured: dict[str, object] = {}

    def fake_run_alert_monitor(**kwargs):
        captured.update(kwargs)
        return AlertMonitorResult(
            checked_at=datetime(2026, 8, 30, 1, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            status="ok",
            source="nmc",
            alert_count=1,
            pushed_count=1,
            message="ok",
        )

    monkeypatch.setattr(
        "assistant.weather_alert_service.run_alert_monitor",
        fake_run_alert_monitor,
    )
    monkeypatch.setattr(sys, "argv", ["assistant", "alerts", "--once"])

    assert cli.main() == 0
    assert captured["once"] is True
    assert captured["interval_seconds"] is None
