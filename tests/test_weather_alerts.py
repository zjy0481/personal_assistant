import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from assistant.app import create_app
from assistant.config import Settings
from assistant.models import WeatherAlert, WeatherAlertEvent
from assistant.push import PushPlusPushAdapter
from assistant.sources.warnings import NmcWarningSource, QWeatherWarningSource
from assistant.storage import SnapshotStore
from assistant.weather_alert_service import WeatherAlertMonitor, run_alert_monitor

CN = ZoneInfo("Asia/Shanghai")


def _settings(*, push_mock: bool = True, **values) -> Settings:
    base = {
        "location": "上海",
        "timezone": "Asia/Shanghai",
        "push_mock": push_mock,
        "weather_alert_enabled": True,
        "weather_alert_types": [],
        "weather_alert_retention_days": 180,
    }
    base.update(values)
    return Settings(**base)


def _alert(
    *,
    alert_id: str = "A-1",
    level: str = "黄色",
    alert_type: str = "暴雨",
    source: str = "nmc",
    status: str = "active",
) -> WeatherAlert:
    return WeatherAlert(
        alert_id=alert_id,
        location="上海",
        alert_type=alert_type,
        level=level,
        title="上海市气象台发布暴雨黄色预警信号",
        description="预计未来6小时有大雨到暴雨。",
        safety_guidance="请注意防范城市内涝。",
        published_at=datetime(2026, 8, 30, 1, 0, tzinfo=CN),
        started_at=datetime(2026, 8, 30, 1, 0, tzinfo=CN),
        ended_at=None,
        source=source,
        source_url=f"https://www.nmc.cn/publish/alarm/{alert_id}.html",
        raw={"source": source},
    )


def _nmc_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/rest/province/all" in url:
            return httpx.Response(200, json=[{"code": "ASH", "name": "上海市"}])
        if "/rest/province/ASH" in url:
            return httpx.Response(
                200,
                json=[{"code": "WwcJd", "province": "上海市", "city": "上海"}],
            )
        if "/rest/weather" in url:
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "real": {
                            "station": {"code": "WwcJd"},
                            "publish_time": "2026-08-30 01:00",
                            "warn": {
                                "alert": "上海市气象台发布暴雨黄色预警信号",
                                "province": "上海市",
                                "city": "上海",
                                "url": "/publish/alarm/A-1.html",
                                "issuecontent": "预计未来6小时有大雨到暴雨。",
                                "issuetime": "",
                                "fmeans": "请注意防范城市内涝。",
                                "signaltype": "暴雨",
                                "signallevel": "黄色",
                                "pic": "https://image.nmc.cn/assets/img/alarm/p0002003.png",
                            },
                        }
                    },
                },
            )
        raise AssertionError(url)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_nmc_warning_source_parses_active_warning() -> None:
    source = NmcWarningSource(client=_nmc_client())

    alerts = source.fetch(["上海"])

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.location == "上海"
    assert alert.level == "黄色"
    assert alert.alert_type == "暴雨"
    assert alert.published_at == datetime(2026, 8, 30, 1, 0, tzinfo=CN)


def test_qweather_v1_warning_source_parses_alerts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/weatheralert/v1/current/" in str(request.url)
        return httpx.Response(
            200,
            json={
                "metadata": {"zeroResult": False},
                "alerts": [
                    {
                        "id": "q-1",
                        "senderName": "上海气象台",
                        "issuedTime": "2026-08-30T01:00+08:00",
                        "messageType": {"code": "alert", "supersedes": []},
                        "eventType": {"name": "暴雨", "code": "1006"},
                        "severity": "moderate",
                        "color": {"code": "yellow"},
                        "effectiveTime": "2026-08-30T01:00+08:00",
                        "expireTime": "2026-08-31T01:00+08:00",
                        "headline": "上海市气象台发布暴雨黄色预警信号",
                        "description": "预计未来6小时有大雨。",
                        "instruction": "注意防范。",
                    }
                ],
            },
        )

    source = QWeatherWarningSource(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        token="jwt-token",
        api_host="https://api.qweather.com",
        latitude=31.23,
        longitude=121.47,
    )

    alerts = source.fetch(["上海"])

    assert len(alerts) == 1
    assert alerts[0].level == "黄色"
    assert alerts[0].alert_id == "q-1"
    assert alerts[0].published_at is not None


def test_storage_weather_alert_timeline_and_cleanup(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "alerts.db")
    now = datetime(2026, 8, 30, 2, 0, tzinfo=CN)
    alert = _alert()

    _, event_id = store.save_weather_alert(
        alert,
        event_type="initial",
        now=now,
    )

    assert event_id > 0
    state = store.load_weather_alert("上海", "暴雨")
    assert state is not None
    assert state.status == "active"
    assert [event.event_type for event in store.list_weather_alert_events()] == [
        "initial"
    ]
    store.mark_weather_alert_push(
        "上海",
        "暴雨",
        event_id,
        status="pushed",
        channel="mock",
        pushed_at=now,
        attempts=1,
    )
    assert store.load_weather_alert("上海", "暴雨").push_status == "pushed"
    old = datetime(2020, 1, 1, tzinfo=CN)
    store.save_weather_alert(
        _alert(status="cancelled", alert_id="old"),
        event_type="cancelled",
        now=old,
    )
    assert store.delete_expired_weather_alerts(days=180) >= 1


class _FakeSource:
    name = "nmc"

    def __init__(self, alerts: list[WeatherAlert]) -> None:
        self.alerts = alerts

    def fetch(self, locations: list[str]) -> list[WeatherAlert]:
        return list(self.alerts)


def test_monitor_pushes_only_initial_and_upgrade(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "monitor.db")
    settings = _settings()
    source = _FakeSource([])
    monitor = WeatherAlertMonitor(
        settings,
        store=store,
        primary=source,
        fallback=None,
    )
    now = datetime(2026, 8, 30, 1, 0, tzinfo=CN)

    source.alerts = [_alert(alert_id="A", level="黄色")]
    first = monitor.check_once(now=now)
    assert first.pushed_count == 1
    assert len(store.list_weather_alert_events()) == 1

    second = monitor.check_once(now=now)
    assert second.pushed_count == 0
    assert len(store.list_weather_alert_events()) == 1

    source.alerts = [_alert(alert_id="A", level="橙色")]
    third = monitor.check_once(now=now)
    assert third.pushed_count == 1
    assert [event.event_type for event in store.list_weather_alert_events()] == [
        "upgraded",
        "initial",
    ]

    source.alerts = [_alert(alert_id="A", level="黄色")]
    fourth = monitor.check_once(now=now)
    assert fourth.pushed_count == 0
    assert store.list_weather_alert_events()[0].event_type == "downgraded"

    source.alerts = []
    fifth = monitor.check_once(now=now)
    assert fifth.pushed_count == 0
    assert store.load_weather_alert("上海", "暴雨").status == "cancelled"
    assert store.list_weather_alert_events()[0].event_type == "cancelled"


def test_monitor_falls_back_to_backup_source(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "fallback.db")
    settings = _settings()
    backup = _FakeSource([_alert(source="qweather", alert_id="Q-1")])
    backup.name = "qweather"

    class _FailingPrimary:
        name = "nmc"

        def fetch(self, locations):
            raise RuntimeError("primary down")

    monitor = WeatherAlertMonitor(
        settings,
        store=store,
        primary=_FailingPrimary(),
        fallback=backup,
    )

    result = monitor.check_once()

    assert result.status == "ok"
    assert result.fallback is True
    assert result.source == "qweather"
    assert store.load_weather_alert("上海", "暴雨") is not None


def test_monitor_pauses_after_consecutive_failures(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "pause.db")
    settings = _settings(
        weather_alert_failure_threshold=1,
        weather_alert_failure_pause_minutes=60,
    )

    class _FailingPrimary:
        name = "nmc"

        def fetch(self, locations):
            raise RuntimeError("primary down")

    monitor = WeatherAlertMonitor(
        settings,
        store=store,
        primary=_FailingPrimary(),
        fallback=None,
    )
    now = datetime(2026, 8, 30, 1, 0, tzinfo=CN)

    first = monitor.check_once(now=now)
    assert first.status == "failed"
    second = monitor.check_once(
        now=datetime(2026, 8, 30, 1, 1, tzinfo=CN)
    )
    assert second.status == "paused"
    assert store.load_latest_weather_alert_run().status == "paused"


def test_weather_alerts_api_returns_state_and_timeline(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "api.db")
    store.save_weather_alert(_alert(), event_type="initial")
    app = create_app(_settings(), store=store)
    client = TestClient(app)

    response = client.get("/api/weather-alerts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["alerts"][0]["alert_type"] == "暴雨"
    assert payload["events"][0]["event_type"] == "initial"

def test_run_alert_monitor_stops_cleanly_on_interrupt(
    monkeypatch,
    capsys,
) -> None:
    settings = _settings()

    class _FakeMonitor:
        def __init__(self) -> None:
            self.checks = 0

        def check_once(self):
            self.checks += 1
            from assistant.weather_alert_service import AlertMonitorResult
            return AlertMonitorResult(
                checked_at=datetime(2026, 8, 30, 1, 0, tzinfo=CN),
                status="ok",
                source="nmc",
                alert_count=0,
                pushed_count=0,
                message="ok",
            )

    def fake_sleep(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "assistant.weather_alert_service.time.sleep",
        fake_sleep,
    )

    result = run_alert_monitor(
        settings=settings,
        monitor=_FakeMonitor(),
        once=False,
        interval_seconds=3,
    )

    assert result.status == "stopped"
    assert "已手动停止" in capsys.readouterr().out


def test_warning_push_uses_persisted_event_type() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": 200, "msg": "ok", "data": "x"})

    alert = _alert()
    alert.event_type = "upgraded"
    adapter = PushPlusPushAdapter(
        token="fixture-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = adapter.send_weather_alert(alert)

    assert result.success is True
    assert "等级升级" in captured["body"]["content"]
    assert "首次发布" not in captured["body"]["content"]
