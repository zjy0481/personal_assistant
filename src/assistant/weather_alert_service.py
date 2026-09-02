"""Independent extreme weather alert monitor with source fallback."""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from assistant.config import Settings
from assistant.models import WeatherAlert, WeatherAlertRun
from assistant.push import PushAdapter, PushResult, create_push_adapter
from assistant.sources.warnings import (
    QWeatherWarningSource,
    WeatherWarningSource,
    level_rank,
    matches_alert_type,
)
from assistant.storage import SnapshotStore

logger = logging.getLogger(__name__)


@dataclass
class AlertMonitorResult:
    """Outcome of one warning source poll."""

    checked_at: datetime
    status: str = "ok"
    source: str = ""
    alert_count: int = 0
    fallback: bool = False
    pushed_count: int = 0
    message: str = ""


class WeatherAlertMonitor:
    """Poll sources, persist state transitions and push only required events."""

    def __init__(
        self,
        settings: Settings,
        *,
        store: SnapshotStore | None = None,
        primary: WeatherWarningSource | None = None,
        fallback: WeatherWarningSource | None = None,
        push_adapter: PushAdapter | None = None,
        db_path: Path | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or SnapshotStore(
            db_path or Path("data/assistant.db")
        )
        self.store.delete_expired_weather_alerts(
            self.settings.weather_alert_retention_days
        )
        self.primary = primary or _create_primary(settings)
        self.fallback_source = fallback
        if self.fallback_source is None:
            qweather = QWeatherWarningSource(settings=settings)
            self.fallback_source = qweather if qweather.configured else None
        self.push_adapter = push_adapter or create_push_adapter(settings)
        self.failure_streak = 0
        self.pause_until: datetime | None = None

    def check_once(self, now: datetime | None = None) -> AlertMonitorResult:
        now = now or datetime.now(ZoneInfo(self.settings.timezone))
        if not self.settings.weather_alert_enabled:
            result = AlertMonitorResult(
                checked_at=now,
                status="disabled",
                message="极端天气预警监测已关闭",
            )
            self._save_run(result)
            return result

        if self._is_paused(now):
            result = AlertMonitorResult(
                checked_at=now,
                status="paused",
                message=f"连续失败，暂停至 {self.pause_until:%Y-%m-%d %H:%M}",
            )
            self._save_run(result)
            return result

        try:
            alerts = self.primary.fetch(self.settings.alert_locations)
            source = self.primary.name
            fallback = False
        except Exception as primary_error:
            logger.warning("主预警源失败：%s", primary_error)
            if self.fallback_source is None:
                self._register_failure(now)
                result = AlertMonitorResult(
                    checked_at=now,
                    status="failed",
                    source=self.primary.name,
                    message=f"主源失败且未配置备用源: {primary_error}",
                )
                self._save_run(result)
                return result
            try:
                alerts = self.fallback_source.fetch(
                    self.settings.alert_locations
                )
                source = self.fallback_source.name
                fallback = True
            except Exception as fallback_error:
                self._register_failure(now)
                result = AlertMonitorResult(
                    checked_at=now,
                    status="failed",
                    source=self.primary.name,
                    fallback=True,
                    message=(
                        f"主源失败: {primary_error}；"
                        f"备用源失败: {fallback_error}"
                    ),
                )
                self._save_run(result)
                return result

        self.failure_streak = 0
        self.pause_until = None
        pushed_count = self._apply_alerts(alerts, source=source, now=now)
        result = AlertMonitorResult(
            checked_at=now,
            status="ok",
            source=source,
            alert_count=len(alerts),
            fallback=fallback,
            pushed_count=pushed_count,
            message=(
                f"已使用备用源" if fallback else "预警检查完成"
            ),
        )
        self._save_run(result)
        return result

    def _is_paused(self, now: datetime) -> bool:
        return self.pause_until is not None and now < self.pause_until

    def _register_failure(self, now: datetime) -> None:
        self.failure_streak += 1
        if self.failure_streak >= self.settings.weather_alert_failure_threshold:
            self.pause_until = now + timedelta(
                minutes=self.settings.weather_alert_failure_pause_minutes
            )

    def _save_run(self, result: AlertMonitorResult) -> None:
        self.store.save_weather_alert_run(
            WeatherAlertRun(
                checked_at=result.checked_at,
                status=result.status,
                source=result.source,
                alert_count=result.alert_count,
                fallback=result.fallback,
                message=result.message,
            )
        )
    def _apply_alerts(
        self,
        alerts: list[WeatherAlert],
        *,
        source: str,
        now: datetime,
    ) -> int:
        current = self._deduplicate_alerts(alerts)
        previous_active = self.store.load_active_weather_alerts(
            types=self.settings.active_weather_alert_types
        )
        seen: set[tuple[str, str]] = set()
        pushed_count = 0

        for alert in current:
            key = (alert.location, alert.alert_type)
            seen.add(key)
            previous = self.store.load_weather_alert(*key)
            event_type, should_push = self._classify(previous, alert)
            alert.updated_at = now
            if event_type:
                alert.event_type = event_type
                alert.push_status = "pending" if should_push else "skipped"
                alert.push_attempts = 0
                alert.pushed_at = None
                alert.last_event_id = 0
                _alert_row, event_id = self.store.save_weather_alert(
                    alert,
                    event_type=event_type,
                    now=now,
                    event_push_status=alert.push_status,
                )
                if should_push and event_id:
                    pushed_count += self._push_alert(
                        alert,
                        event_id,
                        now,
                    )
                continue

            alert.push_status = previous.push_status if previous else ""
            alert.event_type = previous.event_type if previous else ""
            alert.push_attempts = previous.push_attempts if previous else 0
            alert.pushed_at = previous.pushed_at if previous else None
            alert.last_event_id = previous.last_event_id if previous else 0
            self.store.save_weather_alert(alert, now=now)

        for previous in previous_active:
            key = (previous.location, previous.alert_type)
            if key in seen or previous.status != "active":
                continue
            if previous.source != source:
                continue
            cancelled = _copy_alert(previous)
            cancelled.status = "cancelled"
            cancelled.ended_at = now
            cancelled.push_status = "skipped"
            cancelled.event_type = "cancelled"
            cancelled.pushed_at = previous.pushed_at
            cancelled.updated_at = now
            self.store.save_weather_alert(
                cancelled,
                event_type="cancelled",
                now=now,
                event_push_status="skipped",
            )

        retry_limit = self.settings.weather_alert_retry_max
        for state in self.store.load_active_weather_alerts(
            types=self.settings.active_weather_alert_types
        ):
            if state.push_status not in ("pending", "failed"):
                continue
            if state.push_attempts >= retry_limit or not state.last_event_id:
                continue
            pushed_count += self._push_alert(
                state,
                state.last_event_id,
                now,
            )
        return pushed_count

    def _deduplicate_alerts(
        self,
        alerts: list[WeatherAlert],
    ) -> list[WeatherAlert]:
        best: dict[tuple[str, str], WeatherAlert] = {}
        for alert in alerts:
            if not matches_alert_type(
                alert.alert_type,
                self.settings.active_weather_alert_types,
            ):
                continue
            key = (alert.location, alert.alert_type)
            existing = best.get(key)
            if existing is None or level_rank(alert.level) > level_rank(
                existing.level
            ):
                best[key] = alert
        return list(best.values())

    def _classify(
        self,
        previous: WeatherAlert | None,
        current: WeatherAlert,
    ) -> tuple[str | None, bool]:
        if previous is None or previous.status == "cancelled":
            return "initial", True
        previous_rank = level_rank(previous.level)
        current_rank = level_rank(current.level)
        if current_rank > previous_rank:
            return "upgraded", True
        if current_rank < previous_rank:
            return "downgraded", False
        if current.alert_id != previous.alert_id or current.source != previous.source:
            return "updated", False
        return None, False

    def _push_alert(
        self,
        alert: WeatherAlert,
        event_id: int,
        now: datetime,
    ) -> int:
        try:
            result = self.push_adapter.send_weather_alert(alert)
        except Exception as exc:
            logger.error("预警推送渠道异常: %s", exc)
            result = _failed_result(str(exc))
        attempts = alert.push_attempts + 1
        if result.success:
            self.store.mark_weather_alert_push(
                alert.location,
                alert.alert_type,
                event_id,
                status="pushed",
                channel=result.channel,
                pushed_at=now,
                attempts=attempts,
            )
            logger.info("极端天气预警已推送: %s", alert.title)
            return 1
        self.store.mark_weather_alert_push(
            alert.location,
            alert.alert_type,
            event_id,
            status="failed",
            channel=result.channel,
            attempts=attempts,
        )
        logger.error("极端天气预警推送失败: %s", result.message)
        return 0

def _copy_alert(alert: WeatherAlert) -> WeatherAlert:
    return WeatherAlert(
        alert_id=alert.alert_id,
        location=alert.location,
        alert_type=alert.alert_type,
        level=alert.level,
        title=alert.title,
        description=alert.description,
        safety_guidance=alert.safety_guidance,
        status=alert.status,
        event_type=alert.event_type,
        published_at=alert.published_at,
        started_at=alert.started_at,
        ended_at=alert.ended_at,
        source=alert.source,
        source_url=alert.source_url,
        raw=dict(alert.raw or {}),
        push_status=alert.push_status,
        push_attempts=alert.push_attempts,
        pushed_at=alert.pushed_at,
        first_seen_at=alert.first_seen_at,
        updated_at=alert.updated_at,
        last_event_id=alert.last_event_id,
    )


def _failed_result(message: str) -> PushResult:
    return PushResult(
        success=False,
        mode="failed",
        message=message,
    )


def _monitor_now(settings: Settings) -> datetime:
    return datetime.now(ZoneInfo(settings.timezone))


def _print_alert_result(
    result: AlertMonitorResult,
    interval_seconds: int,
) -> None:
    checked_text = "未知"
    next_text = "未知"
    if result.checked_at is not None:
        checked_text = f"{result.checked_at:%Y-%m-%d %H:%M:%S}"
        next_time = result.checked_at + timedelta(seconds=interval_seconds)
        next_text = f"{next_time:%Y-%m-%d %H:%M:%S}"
    summary = (
        f"[{checked_text}] 预警检查：{result.status}；"
        f"源={result.source or '-'}；预警={result.alert_count}；"
        f"推送={result.pushed_count}；下次检查：{next_text}"
    )
    if result.message:
        summary += f"；{result.message}"
    print(summary, flush=True)

def _create_primary(settings: Settings) -> WeatherWarningSource:
    from assistant.sources.warnings import NmcWarningSource

    return NmcWarningSource(timeout=settings.weather_alert_timeout_seconds)


def create_weather_alert_monitor(
    settings: Settings,
    *,
    store: SnapshotStore | None = None,
    primary: WeatherWarningSource | None = None,
    fallback: WeatherWarningSource | None = None,
    push_adapter: PushAdapter | None = None,
    db_path: Path | None = None,
) -> WeatherAlertMonitor:
    return WeatherAlertMonitor(
        settings,
        store=store,
        primary=primary,
        fallback=fallback,
        push_adapter=push_adapter,
        db_path=db_path,
    )


def run_alert_monitor(
    settings: Settings | None = None,
    *,
    store: SnapshotStore | None = None,
    monitor: WeatherAlertMonitor | None = None,
    once: bool = False,
    interval_seconds: int | None = None,
) -> AlertMonitorResult:
    """Run one poll or keep polling as an independent background process."""
    settings = settings or _load_settings()
    store = store or SnapshotStore(Path("data/assistant.db"))
    monitor = monitor or create_weather_alert_monitor(
        settings,
        store=store,
    )
    if once:
        return monitor.check_once()

    interval = (
        interval_seconds
        if interval_seconds is not None
        else settings.weather_alert_interval_seconds
    )
    started = _monitor_now(settings)
    print(
        f"[{started:%Y-%m-%d %H:%M:%S}] 极端天气预警监测已启动，"
        f"每 {interval} 秒检查一次；按 Ctrl+C 停止。",
        flush=True,
    )
    while True:
        try:
            result = monitor.check_once()
            logger.info(
                "预警监测 %s：%s，源=%s，预警=%s，推送=%s",
                result.status,
                result.message,
                result.source,
                result.alert_count,
                result.pushed_count,
            )
            _print_alert_result(result, interval)
        except Exception as exc:
            logger.error("预警监测循环异常: %s", exc)
            print(
                f"[{_monitor_now(settings):%Y-%m-%d %H:%M:%S}] 预警监测循环异常: {exc}",
                flush=True,
            )
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            stopped = AlertMonitorResult(
                checked_at=_monitor_now(settings),
                status="stopped",
                message="已手动停止预警监测",
            )
            print(
                f"[{stopped.checked_at:%Y-%m-%d %H:%M:%S}] {stopped.message}",
                flush=True,
            )
            return stopped


def _load_settings() -> Settings:
    from assistant.config import load_settings

    return load_settings()
