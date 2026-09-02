"""手动验证极端天气预警的发布、升级、降级、解除和推送触发规则。

默认使用临时数据库和模拟推送，不发送真实消息，不影响 data/assistant.db。
使用 --live 时会读取 config.toml/.env 并调用真实推送渠道。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from assistant.config import Settings, load_settings
from assistant.models import WeatherAlert
from assistant.push import MockPushAdapter, PushAdapter, PushResult, create_push_adapter
from assistant.storage import SnapshotStore
from assistant.weather_alert_service import AlertMonitorResult, WeatherAlertMonitor

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CN_TZ = ZoneInfo("Asia/Shanghai")
STEP_TIME = [
    datetime(2026, 8, 30, 8, 0, tzinfo=CN_TZ),
    datetime(2026, 8, 30, 8, 10, tzinfo=CN_TZ),
    datetime(2026, 8, 30, 8, 20, tzinfo=CN_TZ),
    datetime(2026, 8, 30, 8, 30, tzinfo=CN_TZ),
    datetime(2026, 8, 30, 8, 40, tzinfo=CN_TZ),
]


class ScriptedSource:
    """Return whatever alert list the test step assigns."""

    name = "test"

    def __init__(self) -> None:
        self.alerts: list[WeatherAlert] = []

    def fetch(self, locations: list[str]) -> list[WeatherAlert]:
        return list(self.alerts)


class RecordingPushAdapter(PushAdapter):
    """Count warning pushes and optionally forward to a real adapter."""

    def __init__(self, inner: PushAdapter) -> None:
        self.inner = inner
        self.calls: list[tuple[WeatherAlert, PushResult]] = []

    def send_weather_alert(self, alert: WeatherAlert) -> PushResult:
        result = self.inner.send_weather_alert(alert)
        self.calls.append((alert, result))
        return result

    def send_report(self, report):
        return self.inner.send_report(report)


def make_alert(
    level: str,
    *,
    alert_id: str = "TEST-001",
    alert_type: str = "暴雨",
) -> WeatherAlert:
    return WeatherAlert(
        alert_id=alert_id,
        location="上海",
        alert_type=alert_type,
        level=level,
        title=f"上海市气象台发布{alert_type}{level}预警信号",
        description=f"预计未来 6 小时出现{level}强降雨，请注意防范。",
        safety_guidance="避免进入低洼地带，远离临时搭建物。",
        published_at=datetime(2026, 8, 30, 7, 55, tzinfo=CN_TZ),
        started_at=datetime(2026, 8, 30, 7, 55, tzinfo=CN_TZ),
        ended_at=None,
        source="test",
        source_url=f"https://www.nmc.cn/publish/alarm/{alert_id}.html",
        raw={"test": True},
    )


def print_step(
    label: str,
    result: AlertMonitorResult,
    store: SnapshotStore,
    recorder: RecordingPushAdapter,
    previous_calls: int = 0,
    alert_type: str = "暴雨",
) -> None:
    state = store.load_weather_alert("上海", alert_type)
    event = store.list_weather_alert_events(limit=1)
    event_text = (
        f"{event[0].event_type} / 推送状态={event[0].push_status}"
        if event
        else "无事件"
    )
    new_calls = recorder.calls[previous_calls:]
    push_text = "无推送"
    if new_calls:
        pushed = new_calls[-1]
        success = "成功" if pushed[1].success else "失败"
        push_text = f"{pushed[1].channel or 'mock'} / {success}"
    print(f"\n[{label}]")
    print(
        f"  状态={result.status}；源={result.source or '-'}；"
        f"预警={result.alert_count}；本次推送次数={len(new_calls)}"
    )
    print(
        f"  数据库状态={state.status if state else '无'}；"
        f"等级={state.level if state else '-'}"
    )
    print(f"  最新时间线={event_text}")
    print(f"  推送结果={push_text}")


def run(
    *,
    live: bool,
    location: str,
    alert_type: str,
) -> int:
    if live:
        settings = load_settings()
        settings.push_mock = False
        adapter: PushAdapter = create_push_adapter(settings)
    else:
        settings = Settings(
            location=location,
            timezone="Asia/Shanghai",
            push_mock=True,
        )
        adapter = MockPushAdapter()
    recorder = RecordingPushAdapter(adapter)
    source = ScriptedSource()

    with TemporaryDirectory() as tmp_dir:
        store = SnapshotStore(Path(tmp_dir) / "alert-flow.db")
        monitor = WeatherAlertMonitor(
            settings,
            store=store,
            primary=source,
            fallback=None,
            push_adapter=recorder,
        )
        monitor.primary.name = "test"

        steps = [
            ("首次发布", [make_alert("黄色", alert_id="TEST-001", alert_type=alert_type)]),
            ("重复轮询（不应重复推送）", [make_alert("黄色", alert_id="TEST-001", alert_type=alert_type)]),
            ("等级升级（应推送）", [make_alert("橙色", alert_id="TEST-001", alert_type=alert_type)]),
            ("等级降级（不应推送）", [make_alert("黄色", alert_id="TEST-001", alert_type=alert_type)]),
            ("预警解除（不应推送）", []),
        ]
        before_calls = 0
        for index, (label, alerts) in enumerate(steps):
            source.alerts = alerts
            result = monitor.check_once(now=STEP_TIME[index])
            print_step(
                label,
                result,
                store,
                recorder,
                before_calls,
                alert_type=alert_type,
            )
            before_calls = len(recorder.calls)

        events = store.list_weather_alert_events(limit=20)
        expected = ["cancelled", "downgraded", "upgraded", "initial"]
        actual = [event.event_type for event in events[:4]]

        print("\n================ 最终验证 ================")
        print(f"预期时间线（最新优先）：{expected}")
        print(f"实际时间线（最新优先）：{actual}")
        passed = actual == expected
        print("结果：PASS" if passed else "结果：FAIL")
        return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="验证极端天气预警推送流程")
    parser.add_argument(
        "--live",
        action="store_true",
        help="使用真实推送渠道（读取 config.toml/.env），默认仅模拟推送",
    )
    parser.add_argument(
        "--location",
        default="上海",
        help="测试地区，默认上海",
    )
    parser.add_argument(
        "--alert-type",
        default="暴雨",
        help="测试预警类型，默认暴雨",
    )
    args = parser.parse_args()
    return run(live=args.live, location=args.location, alert_type=args.alert_type)


if __name__ == "__main__":
    raise SystemExit(main())