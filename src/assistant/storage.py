"""SQLite snapshot, daily run, content item, chat and weather alert store."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assistant.models import (
    ContentItem,
    Report,
    WeatherAlert,
    WeatherAlertEvent,
    WeatherAlertRun,
    report_from_dict,
    report_to_dict,
)


class SnapshotAlreadyExistsError(RuntimeError):
    """Raised when a same-day snapshot already exists without force mode."""


@dataclass(frozen=True)
class RunStatus:
    """Result of one daily generation/push run for web visibility."""

    report_date: str
    status: str
    channel: str = ""
    short_code: str = ""
    message: str = ""
    created_at: str = ""


class SnapshotStore:
    """Persist snapshots, runs, content items, chat history and warnings."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def save(self, report: Report, *, force: bool = False) -> int:
        """Save one report per day; force replaces an existing same-day row."""
        report_date = report.generated_at.date().isoformat()
        payload = json.dumps(report_to_dict(report), ensure_ascii=False)
        data = report_to_dict(report)
        conn = self._connect()
        try:
            if not force and self._has_report_for_date(conn, report_date):
                raise SnapshotAlreadyExistsError(
                    f"当日日报已存在: {report_date}"
                )
            if force:
                conn.execute(
                    """
                    DELETE FROM report_snapshots
                    WHERE substr(generated_at, 1, 10) = ?
                    """,
                    (report_date,),
                )
            cursor = conn.execute(
                """
                INSERT INTO report_snapshots (
                    title, generated_at, location, timezone, degraded, payload
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    data["title"],
                    data["generated_at"],
                    data["location"],
                    data["timezone"],
                    int(data["degraded"]),
                    payload,
                ),
            )
            self._sync_content_items(conn, report, report_date)
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def has_report_for_date(self, report_date: str) -> bool:
        conn = self._connect()
        try:
            return self._has_report_for_date(conn, report_date)
        finally:
            conn.close()

    def save_run_status(self, status: RunStatus) -> int:
        """Save one run status per report date, replacing earlier rows."""
        created_at = status.created_at or datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM daily_runs WHERE report_date = ?",
                (status.report_date,),
            )
            cursor = conn.execute(
                """
                INSERT INTO daily_runs (
                    report_date, status, channel, short_code,
                    message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    status.report_date,
                    status.status,
                    status.channel,
                    status.short_code,
                    status.message,
                    created_at,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def load_latest_run_status(self) -> RunStatus | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT report_date, status, channel, short_code,
                       message, created_at
                FROM daily_runs
                ORDER BY id DESC
                LIMIT 1
                """,
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return RunStatus(
            report_date=row[0],
            status=row[1],
            channel=row[2],
            short_code=row[3],
            message=row[4],
            created_at=row[5],
        )

    def load_latest(self) -> Report | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT payload
                FROM report_snapshots
                ORDER BY id DESC
                LIMIT 1
                """,
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return report_from_dict(json.loads(row[0]))

    def load_content_items(
        self,
        item_ids: list[str] | None = None,
        limit: int = 200,
    ) -> list[ContentItem]:
        """Load normalized content items, optionally filtered by item id."""
        conn = self._connect()
        try:
            if item_ids:
                placeholders = ",".join("?" for _ in item_ids)
                rows = conn.execute(
                    f"""
                    SELECT title, url, source, published_at, summary,
                           language, category, stars, metadata, item_id,
                           llm_summary, summary_status, summary_model
                    FROM content_items
                    WHERE item_id IN ({placeholders})
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (*item_ids, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT title, url, source, published_at, summary,
                           language, category, stars, metadata, item_id,
                           llm_summary, summary_status, summary_model
                    FROM content_items
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        finally:
            conn.close()
        return [self._item_from_row(row) for row in rows]

    def save_chat_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> int:
        """Append one chat message to a short-lived session."""
        created_at = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO chat_messages (
                    session_id, role, content, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    role,
                    content,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    created_at,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def load_chat_history(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[dict[str, str]]:
        """Load the most recent chat messages for one session."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT role, content
                FROM chat_messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        finally:
            conn.close()
        return [
            {"role": role, "content": content}
            for role, content in reversed(rows)
        ]

    def delete_expired_chat_messages(self, days: int = 7) -> int:
        """Delete chat messages older than the retention window."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM chat_messages WHERE created_at < ?",
                (cutoff,),
            )
            conn.commit()
            return int(cursor.rowcount)
        finally:
            conn.close()
    def save_weather_alert(
        self,
        alert: WeatherAlert,
        *,
        event_type: str | None = None,
        now: datetime | None = None,
        event_push_status: str = "pending",
    ) -> tuple[int, int]:
        """Save current warning state and optionally append a timeline event."""
        now_dt = now or datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        conn = self._connect()
        try:
            existing = conn.execute(
                """
                SELECT first_seen_at, status
                FROM weather_alerts
                WHERE user_id = ? AND location = ? AND alert_type = ?
                """,
                ("default", alert.location, alert.alert_type),
            ).fetchone()
            first_seen = (
                existing[0]
                if existing and existing[1] == "active"
                else now_iso
            )
            cursor = conn.execute(
                """
                INSERT INTO weather_alerts (
                    user_id, alert_id, location, alert_type, level, status,
                    event_type,
                    title, description, safety_guidance, published_at,
                    started_at, ended_at, source, source_url, raw,
                    push_status, push_attempts, pushed_at, first_seen_at,
                    updated_at, last_event_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, location, alert_type) DO UPDATE SET
                    alert_id = excluded.alert_id,
                    level = excluded.level,
                    status = excluded.status,
                    event_type = excluded.event_type,
                    title = excluded.title,
                    description = excluded.description,
                    safety_guidance = excluded.safety_guidance,
                    published_at = excluded.published_at,
                    started_at = excluded.started_at,
                    ended_at = excluded.ended_at,
                    source = excluded.source,
                    source_url = excluded.source_url,
                    raw = excluded.raw,
                    push_status = excluded.push_status,
                    push_attempts = excluded.push_attempts,
                    pushed_at = excluded.pushed_at,
                    first_seen_at = CASE
                        WHEN weather_alerts.status = 'cancelled'
                        THEN excluded.first_seen_at
                        ELSE weather_alerts.first_seen_at
                    END,
                    updated_at = excluded.updated_at,
                    last_event_id = excluded.last_event_id
                """,
                (
                    "default",
                    alert.alert_id,
                    alert.location,
                    alert.alert_type,
                    alert.level,
                    alert.status,
                    alert.event_type,
                    alert.title,
                    alert.description,
                    alert.safety_guidance,
                    alert.published_at.isoformat() if alert.published_at else "",
                    alert.started_at.isoformat() if alert.started_at else "",
                    alert.ended_at.isoformat() if alert.ended_at else "",
                    alert.source,
                    alert.source_url,
                    json.dumps(alert.raw or {}, ensure_ascii=False),
                    alert.push_status,
                    alert.push_attempts,
                    alert.pushed_at.isoformat() if alert.pushed_at else "",
                    first_seen,
                    now_iso,
                    alert.last_event_id,
                ),
            )
            alert_row_id = int(cursor.lastrowid)
            event_id = 0
            if event_type:
                event_cursor = conn.execute(
                    """
                    INSERT INTO weather_alert_events (
                        user_id, alert_id, location, alert_type, level,
                        event_type, title, description, safety_guidance,
                        source, source_url, occurred_at, created_at, raw,
                        push_status, pushed_at, push_channel
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "default",
                        alert.alert_id,
                        alert.location,
                        alert.alert_type,
                        alert.level,
                        event_type,
                        alert.title,
                        alert.description,
                        alert.safety_guidance,
                        alert.source,
                        alert.source_url,
                        now_iso,
                        now_iso,
                        json.dumps(alert.raw or {}, ensure_ascii=False),
                        event_push_status,
                        "",
                        "",
                    ),
                )
                event_id = int(event_cursor.lastrowid)
                conn.execute(
                    """
                    UPDATE weather_alerts
                    SET last_event_id = ?
                    WHERE user_id = ? AND location = ? AND alert_type = ?
                    """,
                    (event_id, "default", alert.location, alert.alert_type),
                )
            conn.commit()
            return alert_row_id, event_id
        finally:
            conn.close()

    def mark_weather_alert_push(
        self,
        location: str,
        alert_type: str,
        event_id: int,
        *,
        status: str,
        channel: str = "",
        pushed_at: datetime | None = None,
        attempts: int = 0,
    ) -> None:
        """Record push outcome on both the current state and timeline event."""
        pushed_at_iso = (
            pushed_at.isoformat() if pushed_at is not None else ""
        )
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE weather_alerts
                SET push_status = ?, push_attempts = ?, pushed_at = ?
                WHERE user_id = ? AND location = ? AND alert_type = ?
                """,
                (
                    status,
                    attempts,
                    pushed_at_iso,
                    "default",
                    location,
                    alert_type,
                ),
            )
            conn.execute(
                """
                UPDATE weather_alert_events
                SET push_status = ?, pushed_at = ?, push_channel = ?
                WHERE id = ? AND user_id = ?
                """,
                (status, pushed_at_iso, channel, event_id, "default"),
            )
            conn.commit()
        finally:
            conn.close()

    def load_weather_alert(
        self,
        location: str,
        alert_type: str,
    ) -> WeatherAlert | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT alert_id, location, alert_type, level, status,
                       event_type,
                       title, description, safety_guidance, published_at,
                       started_at, ended_at, source, source_url, raw,
                       push_status, push_attempts, pushed_at, first_seen_at,
                       updated_at, last_event_id
                FROM weather_alerts
                WHERE user_id = ? AND location = ? AND alert_type = ?
                """,
                ("default", location, alert_type),
            ).fetchone()
        finally:
            conn.close()
        return self._weather_alert_from_row(row) if row else None

    def load_active_weather_alerts(
        self,
        *,
        types: list[str] | None = None,
    ) -> list[WeatherAlert]:
        conn = self._connect()
        try:
            rows = self._weather_alert_rows(
                conn,
                status="active",
                types=types,
                limit=500,
            )
        finally:
            conn.close()
        return [self._weather_alert_from_row(row) for row in rows]

    def list_weather_alerts(
        self,
        *,
        location: str | None = None,
        alert_type: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[WeatherAlert]:
        conn = self._connect()
        try:
            rows = self._weather_alert_rows(
                conn,
                location=location,
                alert_type=alert_type,
                status=status,
                limit=limit,
            )
        finally:
            conn.close()
        return [self._weather_alert_from_row(row) for row in rows]

    def list_weather_alert_events(
        self,
        *,
        location: str | None = None,
        alert_type: str | None = None,
        event_type: str | None = None,
        limit: int = 200,
    ) -> list[WeatherAlertEvent]:
        conn = self._connect()
        try:
            conditions = ["user_id = ?"]
            params: list[object] = ["default"]
            if location:
                conditions.append("location = ?")
                params.append(location)
            if alert_type:
                conditions.append("alert_type = ?")
                params.append(alert_type)
            if event_type:
                conditions.append("event_type = ?")
                params.append(event_type)
            rows = conn.execute(
                f"""
                SELECT id, alert_id, location, alert_type, level, event_type,
                       title, description, safety_guidance, source, source_url,
                       occurred_at, created_at, raw, push_status, pushed_at,
                       push_channel
                FROM weather_alert_events
                WHERE {" AND ".join(conditions)}
                ORDER BY id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        finally:
            conn.close()
        return [self._weather_event_from_row(row) for row in rows]

    def save_weather_alert_run(self, run: WeatherAlertRun) -> int:
        """Append one warning source diagnostic record."""
        now_iso = (
            run.checked_at or datetime.now(timezone.utc)
        ).isoformat()
        created_at = (
            run.created_at or datetime.now(timezone.utc)
        ).isoformat()
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO weather_alert_runs (
                    user_id, checked_at, status, source, alert_count,
                    fallback, message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "default",
                    now_iso,
                    run.status,
                    run.source,
                    run.alert_count,
                    int(run.fallback),
                    run.message,
                    created_at,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def load_latest_weather_alert_run(self) -> WeatherAlertRun | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT id, checked_at, status, source, alert_count,
                       fallback, message, created_at
                FROM weather_alert_runs
                ORDER BY id DESC
                LIMIT 1
                """,
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return WeatherAlertRun(
            id=row[0],
            checked_at=_parse_iso(row[1]),
            status=row[2],
            source=row[3],
            alert_count=row[4],
            fallback=bool(row[5]),
            message=row[6],
            created_at=_parse_iso(row[7]),
        )

    def delete_expired_weather_alerts(self, days: int = 180) -> int:
        """Delete old warning events and resolved states."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()
        conn = self._connect()
        try:
            event_cursor = conn.execute(
                """
                DELETE FROM weather_alert_events
                WHERE occurred_at < ? AND occurred_at != ''
                """,
                (cutoff,),
            )
            state_cursor = conn.execute(
                """
                DELETE FROM weather_alerts
                WHERE status = 'cancelled'
                  AND updated_at < ? AND updated_at != ''
                """,
                (cutoff,),
            )
            conn.commit()
            return int(event_cursor.rowcount) + int(state_cursor.rowcount)
        finally:
            conn.close()

    @staticmethod
    def _has_report_for_date(conn: sqlite3.Connection, report_date: str) -> bool:
        row = conn.execute(
            """
            SELECT 1
            FROM report_snapshots
            WHERE substr(generated_at, 1, 10) = ?
            LIMIT 1
            """,
            (report_date,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _sync_content_items(
        conn: sqlite3.Connection,
        report: Report,
        report_date: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for block in report.blocks:
            for item in block.items:
                conn.execute(
                    """
                    INSERT INTO content_items (
                        item_id, title, url, source, published_at, language, category, stars, block_kind,
                        report_date, summary, llm_summary, summary_status,
                        summary_model, metadata, first_seen_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(item_id) DO UPDATE SET
                        title = excluded.title,
                        url = excluded.url,
                        source = excluded.source,
                        published_at = excluded.published_at,
                        language = excluded.language,
                        category = excluded.category,
                        stars = excluded.stars,
                        block_kind = excluded.block_kind,
                        report_date = excluded.report_date,
                        summary = excluded.summary,
                        llm_summary = excluded.llm_summary,
                        summary_status = excluded.summary_status,
                        summary_model = excluded.summary_model,
                        metadata = excluded.metadata,
                        updated_at = excluded.updated_at
                    """,
                    (
                        item.stable_id,
                        item.title,
                        item.url,
                        item.source,
                        item.published_at.isoformat() if item.published_at else "",
                        item.language,
                        item.category,
                        item.stars,
                        block.kind,
                        report_date,
                        item.summary,
                        item.llm_summary,
                        item.summary_status,
                        item.summary_model,
                        json.dumps(item.metadata, ensure_ascii=False),
                        now,
                        now,
                    ),
                )

    @staticmethod
    def _item_from_row(row: tuple) -> ContentItem:
        published_at = None
        if row[3]:
            try:
                published_at = datetime.fromisoformat(row[3])
            except ValueError:
                published_at = None
        metadata = json.loads(row[8]) if row[8] else {}
        return ContentItem(
            title=row[0],
            url=row[1],
            source=row[2],
            published_at=published_at,
            summary=row[4] or "",
            language=row[5] or "",
            category=row[6] or "",
            stars=row[7],
            metadata=metadata,
            item_id=row[9] or "",
            llm_summary=row[10] or "",
            summary_status=row[11] or "",
            summary_model=row[12] or "",
        )

    @staticmethod
    def _weather_alert_rows(
        conn: sqlite3.Connection,
        *,
        location: str | None = None,
        alert_type: str | None = None,
        status: str | None = None,
        types: list[str] | None = None,
        limit: int = 500,
    ) -> list[sqlite3.Row]:
        conditions = ["user_id = ?"]
        params: list[object] = ["default"]
        if location:
            conditions.append("location = ?")
            params.append(location)
        if alert_type:
            conditions.append("alert_type = ?")
            params.append(alert_type)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if types:
            placeholders = ",".join("?" for _ in types)
            conditions.append(f"alert_type IN ({placeholders})")
            params.extend(types)
        return conn.execute(
            f"""
            SELECT alert_id, location, alert_type, level, status,
                       event_type,
                   title, description, safety_guidance, published_at,
                   started_at, ended_at, source, source_url, raw,
                   push_status, push_attempts, pushed_at, first_seen_at,
                   updated_at, last_event_id
            FROM weather_alerts
            WHERE {" AND ".join(conditions)}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()

    @staticmethod
    def _weather_alert_from_row(row: tuple) -> WeatherAlert:
        return WeatherAlert(
            alert_id=row[0],
            location=row[1],
            alert_type=row[2],
            level=row[3],
            status=row[4],
            event_type=row[5],
            title=row[6],
            description=row[7],
            safety_guidance=row[8],
            published_at=_parse_iso(row[9]),
            started_at=_parse_iso(row[10]),
            ended_at=_parse_iso(row[11]),
            source=row[12],
            source_url=row[13],
            raw=json.loads(row[14]) if row[14] else {},
            push_status=row[15],
            push_attempts=int(row[16] or 0),
            pushed_at=_parse_iso(row[17]),
            first_seen_at=_parse_iso(row[18]),
            updated_at=_parse_iso(row[19]),
            last_event_id=int(row[20] or 0),
        )

    @staticmethod
    def _weather_event_from_row(row: tuple) -> WeatherAlertEvent:
        return WeatherAlertEvent(
            event_id=row[0],
            alert_id=row[1],
            location=row[2],
            alert_type=row[3],
            level=row[4],
            event_type=row[5],
            title=row[6],
            description=row[7],
            safety_guidance=row[8],
            source=row[9],
            source_url=row[10],
            occurred_at=_parse_iso(row[11]),
            created_at=_parse_iso(row[12]),
            raw=json.loads(row[13]) if row[13] else {},
            push_status=row[14],
            pushed_at=_parse_iso(row[15]),
            push_channel=row[16],
        )

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS report_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                location TEXT NOT NULL,
                timezone TEXT NOT NULL,
                degraded INTEGER NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TEXT NOT NULL,
                status TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT '',
                short_code TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS content_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                url TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                stars INTEGER,
                block_kind TEXT NOT NULL DEFAULT '',
                report_date TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                llm_summary TEXT NOT NULL DEFAULT '',
                summary_status TEXT NOT NULL DEFAULT '',
                summary_model TEXT NOT NULL DEFAULT '',
                metadata TEXT NOT NULL DEFAULT '{}',
                first_seen_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weather_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'default',
                alert_id TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                level TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                event_type TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                safety_guidance TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL DEFAULT '',
                ended_at TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                raw TEXT NOT NULL DEFAULT '{}',
                push_status TEXT NOT NULL DEFAULT '',
                push_attempts INTEGER NOT NULL DEFAULT 0,
                pushed_at TEXT NOT NULL DEFAULT '',
                first_seen_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                last_event_id INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, location, alert_type)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weather_alert_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'default',
                alert_id TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                level TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                safety_guidance TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                occurred_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                raw TEXT NOT NULL DEFAULT '{}',
                push_status TEXT NOT NULL DEFAULT '',
                pushed_at TEXT NOT NULL DEFAULT '',
                push_channel TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weather_alert_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'default',
                checked_at TEXT NOT NULL,
                status TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                alert_count INTEGER NOT NULL DEFAULT 0,
                fallback INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(weather_alerts)").fetchall()}
        if "event_type" not in columns:
            conn.execute(
                "ALTER TABLE weather_alerts ADD COLUMN event_type TEXT NOT NULL DEFAULT ''"
            )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_daily_runs_report_date
            ON daily_runs(report_date)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_content_items_item_id
            ON content_items(item_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
            ON chat_messages(session_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_weather_alerts_location_type
            ON weather_alerts(location, alert_type)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_weather_alert_events_occurred_at
            ON weather_alert_events(occurred_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_weather_alert_runs_checked_at
            ON weather_alert_runs(checked_at)
            """
        )
        return conn


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
