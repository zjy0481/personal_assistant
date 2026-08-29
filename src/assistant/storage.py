"""SQLite snapshot, daily run, content item and chat message store."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assistant.models import (
    ContentItem,
    Report,
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
    """Persist snapshot, run status, content items and chat history."""

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
        return conn