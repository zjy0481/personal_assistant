"""SQLite snapshot, daily run, content item, chat and weather alert store."""

import json
import sqlite3

import re
from collections import Counter

try:
    import jieba
except ImportError:
    jieba = None
from dataclasses import dataclass
from typing import Any
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assistant.models import (
    ContentItem,
    Favorite,
    GitHubRepo,
    NewsTerm,
    Report,
    WeatherAlert,
    WeatherAlertEvent,
    WeatherAlertRun,
    report_from_dict,
    report_to_dict,
)



_STOP_WORDS = {
    "\u7684", "\u4e86", "\u5728", "\u662f", "\u6709", "\u548c", "\u4e0e", "\u53ca", "\u6216", "\u800c", "\u5bf9", "\u4e3a", "\u4ee5", "\u4ece", "\u5230", "\u5c06", "\u7b49", "\u4e2d", "\u8fd9", "\u90a3", "\u4e00", "\u4e0d", "\u4e5f", "\u90fd", "\u5e76", "\u4f46", "\u88ab", "\u4e8e", "\u5176", "\u4e4b", "\u53c8", "\u5c31", "\u5f88", "\u66f4", "\u6700", "\u8fd8", "\u53ef", "\u80fd", "\u4f1a", "\u8981", "\u8ba9", "\u628a", "\u5df2", "\u6ca1", "\u5982",
    "the", "a", "an", "and", "of", "to", "in", "on", "for", "with", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "can", "could", "may", "might", "must", "not", "no", "so", "if", "but", "than",
    "then", "very", "at", "by", "from", "as", "or", "this", "that", "these", "those", "it",
    "its", "he", "him", "his", "her", "hers", "she", "they", "them", "their", "theirs", "we",
    "us", "our", "ours", "you", "your", "yours", "i", "me", "my", "mine", "who", "whom",
    "whose", "which", "what", "when", "where", "why", "how", "about", "above", "across",
    "after", "against", "along", "among", "around", "before", "behind", "below", "beneath",
    "beside", "between", "beyond", "despite", "down", "during", "except", "inside", "into",
    "near", "onto", "outside", "over", "through", "toward", "under", "until", "upon", "via",
    "while", "within", "without", "only", "more", "most", "some", "any", "all", "each", "both",
    "few", "many", "much", "other", "another", "such", "also", "still", "just", "now", "then",
    "first", "last", "next", "today", "yesterday", "tomorrow", "new", "latest", "old", "good",
    "great", "big", "small", "high", "low", "top", "best", "time", "times", "year", "years",
    "day", "days", "week", "weeks", "month", "months", "make", "makes", "made", "get", "gets",
    "got", "take", "takes", "took", "use", "uses", "used", "report", "reports", "reported",
    "news", "said", "says", "say", "told", "tells", "added", "adds", "according", "update",
    "updates", "updated", "release", "releases", "released", "launch", "launches", "launched",
    "show", "shows", "showed", "come", "comes", "came", "go", "goes", "went",
}

_NOUN_POS = {"n", "nr", "ns", "nt", "nz", "ng", "nrt", "vn"}

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9][A-Za-z0-9\-_.]{1,}")


def _tokenize_news_text(text: str) -> list[str]:
    """Extract topical Chinese nouns and meaningful English terms."""
    if not text:
        return []
    value = re.sub(r"[\r\n]+", " ", text)
    if jieba is not None:
        try:
            import jieba.posseg as posseg
            segments = list(posseg.cut(value))
        except Exception:
            segments = [(item, "") for item in jieba.cut(value)]
    else:
        segments = [(item, "") for item in _TOKEN_RE.findall(value)]

    words: list[str] = []
    for raw, flag in segments:
        word = re.sub(r"^[^\w\u4e00-\u9fff]+|[^\w\u4e00-\u9fff]+$", "", str(raw))
        key = word.strip().lower()
        if not key or key in _STOP_WORDS:
            continue
        if flag == "eng":
            if len(key) < 3 and not word.isupper():
                continue
            if not re.match(r"^[a-z0-9][a-z0-9\-_.]*$", key):
                continue
            words.append(key)
        elif flag and flag in _NOUN_POS:
            if len(key) >= 2:
                words.append(key)
        elif not flag:
            if re.search(r"[\u4e00-\u9fff]", word):
                if len(key) >= 2:
                    words.append(key)
            elif len(key) >= 3 and re.match(r"^[a-z0-9][a-z0-9\-_.]*$", key):
                words.append(key)
    return words


def _normalize_repo(title: str, url: str, metadata: dict) -> str:
    candidates = [url, title]
    if metadata:
        candidates.append(str(metadata.get("repo") or ""))
    for value in candidates:
        match = re.search(r"github\.com[/:]([^/]+)/([^/?#]+)", value)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    return (title or url).strip()


def _date_range(start_date: str, end_date: str) -> list[str]:
    from datetime import date as date_type
    current = date_type.fromisoformat(start_date)
    end = date_type.fromisoformat(end_date)
    result: list[str] = []
    while current <= end:
        result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def _favorite_from_row(row: tuple) -> Favorite:
    return Favorite(
        item_id=row[0],
        report_date=row[1],
        block_kind=row[2],
        title=row[3],
        url=row[4],
        source=row[5],
        note=row[6],
        status=row[7],
        created_at=row[8],
        updated_at=row[9],
        user_id=row[10],
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

    def save_favorite(
        self,
        *,
        item_id: str,
        report_date: str = "",
        block_kind: str = "",
        title: str = "",
        url: str = "",
        source: str = "",
        note: str = "",
        status: str = "active",
    ) -> int:
        """Save or restore one favorite row idempotently."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO favorites (
                    user_id, item_id, report_date, block_kind, title, url,
                    source, note, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, item_id) DO UPDATE SET
                    report_date = excluded.report_date,
                    block_kind = excluded.block_kind,
                    title = excluded.title,
                    url = excluded.url,
                    source = excluded.source,
                    note = excluded.note,
                    status = 'active',
                    updated_at = excluded.updated_at
                """,
                (
                    "default", item_id, report_date, block_kind, title, url,
                    source, note, status, now, now,
                ),
            )
            row = conn.execute(
                """
                SELECT id FROM favorites
                WHERE user_id = ? AND item_id = ? AND status = 'active'
                """,
                ("default", item_id),
            ).fetchone()
            conn.commit()
            return int(row[0]) if row else 0
        finally:
            conn.close()

    def remove_favorite(self, item_id: str) -> None:
        """Mark one favorite row removed; history is kept for re-favoriting."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE favorites
                SET status = 'removed', updated_at = ?
                WHERE user_id = ? AND item_id = ?
                """,
                (now, "default", item_id),
            )
            conn.commit()
        finally:
            conn.close()

    def list_favorites(
        self,
        *,
        block_kind: str | None = None,
        status: str = "active",
        limit: int = 500,
    ) -> list[Favorite]:
        conn = self._connect()
        try:
            conditions = ["user_id = ?", "status = ?"]
            params: list[object] = ["default", status]
            if block_kind:
                conditions.append("block_kind = ?")
                params.append(block_kind)
            rows = conn.execute(
                f"""
                SELECT item_id, report_date, block_kind, title, url,
                       source, note, status, created_at, updated_at, user_id
                FROM favorites
                WHERE {" AND ".join(conditions)}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        finally:
            conn.close()
        return [_favorite_from_row(row) for row in rows]

    def load_favorite(self, item_id: str) -> Favorite | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT item_id, report_date, block_kind, title, url,
                       source, note, status, created_at, updated_at, user_id
                FROM favorites
                WHERE user_id = ? AND item_id = ?
                """,
                ("default", item_id),
            ).fetchone()
        finally:
            conn.close()
        return _favorite_from_row(row) if row else None

    def latest_report_date(self) -> str | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT MAX(substr(generated_at, 1, 10)) FROM report_snapshots"
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row and row[0] else None

    def ensure_content_items_for_range(
        self,
        start_date: str,
        end_date: str,
    ) -> int:
        """Backfill normalized content items from historical report snapshots."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT generated_at, payload
                FROM report_snapshots
                WHERE substr(generated_at, 1, 10) BETWEEN ? AND ?
                ORDER BY generated_at
                """,
                (start_date, end_date),
            ).fetchall()
            count = 0
            for generated_at, payload in rows:
                report_date = generated_at[:10]
                try:
                    report = report_from_dict(json.loads(payload))
                except (ValueError, KeyError, TypeError):
                    continue
                self._sync_content_items(conn, report, report_date)
                count += 1
            conn.commit()
            return count
        finally:
            conn.close()

    def recompute_trends(self, start_date: str, end_date: str, *, min_count: int = 1) -> int:
        """Aggregate news keywords and GitHub metrics for a date range."""
        self.ensure_content_items_for_range(start_date, end_date)
        dates = _date_range(start_date, end_date)
        if not dates:
            return 0
        conn = self._connect()
        try:
            for report_date in dates:
                self._write_news_trends(conn, report_date, min_count)
                self._write_github_trends(conn, report_date)
                count = sum(
                    row[0]
                    for row in conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM news_trend_snapshots
                        WHERE user_id = ? AND report_date = ?
                        """,
                        ("default", report_date),
                    ).fetchall()
                )
                status = "ok" if count else "no_data"
                self._mark_trend_run(conn, report_date, status)
            conn.commit()
            return len(dates)
        finally:
            conn.close()

    def load_news_trends(
        self,
        start_date: str,
        end_date: str,
    ) -> list[NewsTerm]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT report_date, word, count, rank
                FROM news_trend_snapshots
                WHERE user_id = ? AND report_date BETWEEN ? AND ?
                ORDER BY report_date, rank
                """,
                ("default", start_date, end_date),
            ).fetchall()
        finally:
            conn.close()
        return [NewsTerm(*row) for row in rows]

    def load_github_trends(
        self,
        start_date: str,
        end_date: str,
    ) -> list[GitHubRepo]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT report_date, repo, stars, new_stars, rank, appearances
                FROM github_trend_snapshots
                WHERE user_id = ? AND report_date BETWEEN ? AND ?
                ORDER BY report_date, rank
                """,
                ("default", start_date, end_date),
            ).fetchall()
        finally:
            conn.close()
        return [GitHubRepo(*row) for row in rows]

    def delete_expired_trend_snapshots(self, days: int = 180) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        conn = self._connect()
        try:
            news = conn.execute(
                "DELETE FROM news_trend_snapshots WHERE report_date < ?",
                (cutoff,),
            )
            github = conn.execute(
                "DELETE FROM github_trend_snapshots WHERE report_date < ?",
                (cutoff,),
            )
            runs = conn.execute(
                "DELETE FROM trend_runs WHERE report_date < ?",
                (cutoff,),
            )
            conn.commit()
            return int(news.rowcount + github.rowcount + runs.rowcount)
        finally:
            conn.close()

    def _write_news_trends(
        self,
        conn: sqlite3.Connection,
        report_date: str,
        min_count: int = 1,
    ) -> None:
        counter: Counter = Counter()
        row = conn.execute(
            """
            SELECT payload
            FROM report_snapshots
            WHERE substr(generated_at, 1, 10) = ?
            """,
            (report_date,),
        ).fetchone()
        if row:
            try:
                report = report_from_dict(json.loads(row[0]))
            except (ValueError, KeyError, TypeError):
                report = None
            if report:
                for block in report.blocks:
                    if block.kind != "news":
                        continue
                    for item in block.items:
                        text = item.title or item.summary or item.llm_summary
                        for word in _tokenize_news_text(text):
                            counter[word] += 1
        conn.execute(
            "DELETE FROM news_trend_snapshots WHERE user_id = ? AND report_date = ?",
            ("default", report_date),
        )
        for rank, (word, count) in enumerate(
            sorted((item for item in counter.items() if item[1] >= min_count), key=lambda item: (-item[1], item[0]))[:10],
            start=1,
        ):
            conn.execute(
                """
                INSERT INTO news_trend_snapshots (
                    user_id, report_date, word, count, rank, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "default", report_date, word, count, rank,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def _write_github_trends(
        self,
        conn: sqlite3.Connection,
        report_date: str,
    ) -> None:
        repo_data: dict[str, int] = {}
        row = conn.execute(
            """
            SELECT payload
            FROM report_snapshots
            WHERE substr(generated_at, 1, 10) = ?
            """,
            (report_date,),
        ).fetchone()
        if row:
            try:
                report = report_from_dict(json.loads(row[0]))
            except (ValueError, KeyError, TypeError):
                report = None
            if report:
                for block in report.blocks:
                    if block.kind != "github":
                        continue
                    for item in block.items:
                        repo = _normalize_repo(item.title, item.url, item.metadata)
                        value = int(item.stars or 0)
                        if repo not in repo_data or value > repo_data[repo]:
                            repo_data[repo] = value
        conn.execute(
            "DELETE FROM github_trend_snapshots WHERE user_id = ? AND report_date = ?",
            ("default", report_date),
        )
        ordered = sorted(repo_data.items(), key=lambda item: (-item[1], item[0]))
        for rank, (repo, stars) in enumerate(ordered, start=1):
            previous = conn.execute(
                """
                SELECT stars FROM github_trend_snapshots
                WHERE user_id = ? AND repo = ? AND report_date < ?
                ORDER BY report_date DESC
                LIMIT 1
                """,
                ("default", repo, report_date),
            ).fetchone()
            previous_stars = int(previous[0]) if previous else None
            new_stars = stars - previous_stars if previous_stars is not None else None
            conn.execute(
                """
                INSERT INTO github_trend_snapshots (
                    user_id, report_date, repo, stars, new_stars, rank,
                    appearances, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "default", report_date, repo, stars, new_stars, rank, 0,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        for repo in repo_data:
            count = conn.execute(
                """
                SELECT COUNT(DISTINCT report_date)
                FROM github_trend_snapshots
                WHERE user_id = ? AND repo = ?
                """,
                ("default", repo),
            ).fetchone()
            appearances = int(count[0]) if count else 0
            conn.execute(
                """
                UPDATE github_trend_snapshots
                SET appearances = ?
                WHERE user_id = ? AND repo = ?
                """,
                (appearances, "default", repo),
            )
    def _mark_trend_run(
        self,
        conn: sqlite3.Connection,
        report_date: str,
        status: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO trend_runs (
                user_id, report_date, status, message, created_at
            ) VALUES (?, ?, ?, '', ?)
            ON CONFLICT(user_id, report_date) DO UPDATE SET
                status = excluded.status,
                message = excluded.message,
                created_at = excluded.created_at
            """,
            ("default", report_date, status, now),
        )

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
    def save_wecom_ai_message(
        self,
        *,
        msgid: str,
        req_id: str = "",
        chat_id: str = "",
        chat_type: str = "",
        from_userid: str = "",
        msg_type: str = "",
        content: str = "",
        status: str = "processing",
    ) -> int | None:
        """Insert a unique smart-robot callback; return None for duplicates."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO wecom_ai_messages (
                    user_id, msgid, req_id, chat_id, chat_type,
                    from_userid, msg_type, content, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "default", msgid, req_id, chat_id, chat_type,
                    from_userid, msg_type, content, status, now, now,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid) if cursor.rowcount else None
        finally:
            conn.close()

    def mark_wecom_ai_message(
        self,
        msgid: str,
        status: str,
        *,
        answer: str = "",
        error: str = "",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE wecom_ai_messages
                SET status = ?, answer = ?, error = ?, updated_at = ?
                WHERE msgid = ?
                """,
                (status, answer, error, now, msgid),
            )
            conn.commit()
        finally:
            conn.close()

    def load_wecom_ai_message(self, msgid: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT msgid, req_id, chat_id, chat_type, from_userid,
                       msg_type, content, status, answer, error,
                       created_at, updated_at
                FROM wecom_ai_messages
                WHERE msgid = ?
                """,
                (msgid,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return {
            "msgid": row[0],
            "req_id": row[1],
            "chat_id": row[2],
            "chat_type": row[3],
            "from_userid": row[4],
            "msg_type": row[5],
            "content": row[6],
            "status": row[7],
            "answer": row[8],
            "error": row[9],
            "created_at": row[10],
            "updated_at": row[11],
        }

    def delete_expired_wecom_ai_messages(self, days: int = 180) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM wecom_ai_messages WHERE created_at < ?",
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
            CREATE TABLE IF NOT EXISTS wecom_ai_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'default',
                msgid TEXT NOT NULL UNIQUE,
                req_id TEXT NOT NULL DEFAULT '',
                chat_id TEXT NOT NULL DEFAULT '',
                chat_type TEXT NOT NULL DEFAULT '',
                from_userid TEXT NOT NULL DEFAULT '',
                msg_type TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'processing',
                answer TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_wecom_ai_messages_created_at
            ON wecom_ai_messages(created_at)
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'default',
                item_id TEXT NOT NULL,
                report_date TEXT NOT NULL DEFAULT '',
                block_kind TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, item_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news_trend_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'default',
                report_date TEXT NOT NULL,
                word TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                rank INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, report_date, word)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS github_trend_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'default',
                report_date TEXT NOT NULL,
                repo TEXT NOT NULL,
                stars INTEGER NOT NULL DEFAULT 0,
                new_stars INTEGER,
                rank INTEGER NOT NULL DEFAULT 0,
                appearances INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, report_date, repo)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trend_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'default',
                report_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(user_id, report_date)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_favorites_user_status
            ON favorites(user_id, status, updated_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_news_trends_date
            ON news_trend_snapshots(user_id, report_date)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_github_trends_date
            ON github_trend_snapshots(user_id, report_date)
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
