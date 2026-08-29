"""SQLite snapshot and daily run status store."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from assistant.models import Report, report_from_dict, report_to_dict


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
    """Persist latest report snapshot and daily run status."""

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
            CREATE INDEX IF NOT EXISTS idx_daily_runs_report_date
            ON daily_runs(report_date)
            """
        )
        return conn