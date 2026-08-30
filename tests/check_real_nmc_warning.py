"""Use a currently active NMC warning to verify the real parsing pipeline.

Read-only for the public NMC endpoint. The database is created in a temporary
directory. Push is mocked by default; use --live to send real messages.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from assistant.config import Settings, load_settings
from assistant.models import weather_alert_event_to_dict, weather_alert_to_dict
from assistant.push import MockPushAdapter, create_push_adapter
from assistant.sources.warnings import NmcWarningSource
from assistant.storage import SnapshotStore
from assistant.weather_alert_service import WeatherAlertMonitor

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _alert_dict(alert):
    return weather_alert_to_dict(alert)


def _event_dict(event):
    return weather_alert_event_to_dict(event)


def run(location: str, live: bool) -> int:
    if live:
        settings = load_settings()
        settings.push_mock = False
        adapter = create_push_adapter(settings)
    else:
        settings = Settings(
            location=location,
            timezone="Asia/Shanghai",
            push_mock=True,
            weather_alert_locations=[location],
        )
        adapter = MockPushAdapter()

    with TemporaryDirectory() as tmp_dir:
        store = SnapshotStore(Path(tmp_dir) / "real-nmc.db")
        monitor = WeatherAlertMonitor(
            settings,
            store=store,
            primary=NmcWarningSource(),
            fallback=None,
            push_adapter=adapter,
        )
        result = monitor.check_once()
        active_alerts = store.list_weather_alerts(status="active")
        events = store.list_weather_alert_events(limit=20)

        validation = {
            "source_reached": result.status == "ok",
            "alert_parsed": len(active_alerts) > 0,
            "has_type": bool(active_alerts and active_alerts[0].alert_type),
            "has_level": bool(active_alerts and active_alerts[0].level),
            "has_description": bool(active_alerts and active_alerts[0].description),
            "has_safety_guidance": bool(
                active_alerts and active_alerts[0].safety_guidance
            ),
            "has_source_url": bool(
                active_alerts and active_alerts[0].source_url.startswith("http")
            ),
            "timeline_recorded": len(events) > 0,
            "push_requested": (
                result.pushed_count > 0
                if live
                else True
            ),
        }
        payload = {
            "location": location,
            "push_mode": "live" if live else "mock",
            "checked_at": (
                result.checked_at.isoformat()
                if isinstance(result.checked_at, datetime)
                else None
            ),
            "check_result": {
                "status": result.status,
                "source": result.source,
                "alert_count": result.alert_count,
                "pushed_count": result.pushed_count,
                "message": result.message,
            },
            "validation": validation,
            "active_alerts": [
                _alert_dict(alert) for alert in active_alerts
            ],
            "events": [_event_dict(event) for event in events],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))

        ok = all(validation.values())
        print("\n结果：PASS" if ok else "\n结果：FAIL")
        return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="用真实中央气象台当前活跃预警验证解析与推送触发"
    )
    parser.add_argument(
        "--location",
        default="金寨",
        help="当前有生效预警的地区，默认安徽六安金寨",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="读取 config.toml/.env 并调用真实推送渠道，默认只模拟推送",
    )
    args = parser.parse_args()
    return run(args.location, args.live)


if __name__ == "__main__":
    raise SystemExit(main())