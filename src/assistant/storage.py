"""SQLite snapshot store for canonical daily reports."""

import json
import sqlite3
from pathlib import Path

from assistant.models import Report, report_from_dict, report_to_dict


class SnapshotStore:
    """Persist the latest report snapshot so push/web reuse one artifact."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def save(self, report: Report) -> int:
        payload = json.dumps(report_to_dict(report), ensure_ascii=False)
        data = report_to_dict(report)
        conn = self._connect()
        try:
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
        return conn