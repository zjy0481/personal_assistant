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
