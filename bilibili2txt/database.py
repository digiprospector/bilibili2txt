from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .models import Task, now_iso


SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    bvid TEXT PRIMARY KEY,
    aid INTEGER,
    cid INTEGER,
    title TEXT NOT NULL,
    up_name TEXT NOT NULL,
    up_mid INTEGER,
    pubdate INTEGER,
    duration INTEGER NOT NULL DEFAULT 0,
    source_url TEXT NOT NULL,
    video_status TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    bvid TEXT NOT NULL,
    task_file TEXT,
    queue_state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    last_error TEXT,
    created_at TEXT NOT NULL,
    submitted_at TEXT,
    completed_at TEXT,
    FOREIGN KEY (bvid) REFERENCES videos(bvid)
);

CREATE TABLE IF NOT EXISTS rendered_files (
    bvid TEXT NOT NULL,
    text_file TEXT NOT NULL,
    markdown_file TEXT,
    ai_provider TEXT,
    render_status TEXT NOT NULL,
    last_error TEXT,
    rendered_at TEXT,
    PRIMARY KEY (bvid, text_file)
);
"""

MAIN_VIDEO_COLUMNS = {
    "bvid",
    "up_name",
    "up_mid",
    "title",
    "link",
    "pubdate",
    "duration",
    "cid",
    "status",
    "timestamp",
}


class ClientDatabase:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def video_exists(self, bvid: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM videos WHERE bvid = ?", (bvid,)).fetchone()
        return row is not None

    def upsert_video(self, task: Task) -> None:
        now = now_iso()
        with self.connect() as conn:
            existing = conn.execute("SELECT first_seen_at FROM videos WHERE bvid = ?", (task.bvid,)).fetchone()
            first_seen = existing["first_seen_at"] if existing else now
            conn.execute(
                """
                INSERT INTO videos (
                    bvid, aid, cid, title, up_name, up_mid, pubdate, duration,
                    source_url, video_status, first_seen_at, last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bvid) DO UPDATE SET
                    aid=excluded.aid,
                    cid=excluded.cid,
                    title=excluded.title,
                    up_name=excluded.up_name,
                    up_mid=excluded.up_mid,
                    pubdate=excluded.pubdate,
                    duration=excluded.duration,
                    source_url=excluded.source_url,
                    video_status=excluded.video_status,
                    last_seen_at=excluded.last_seen_at
                """,
                (
                    task.bvid,
                    task.aid,
                    task.cid,
                    task.title,
                    task.up_name,
                    task.up_mid,
                    task.pubdate,
                    task.duration,
                    task.source_url,
                    task.status,
                    first_seen,
                    now,
                ),
            )

    def upsert_task(self, task: Task, task_file: Path | None, queue_state: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, bvid, task_file, queue_state, attempts, max_attempts,
                    last_error, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    task_file=excluded.task_file,
                    queue_state=excluded.queue_state,
                    attempts=excluded.attempts,
                    max_attempts=excluded.max_attempts,
                    last_error=excluded.last_error
                """,
                (
                    task.task_id,
                    task.bvid,
                    str(task_file) if task_file else None,
                    queue_state,
                    task.attempts,
                    task.max_attempts,
                    task.last_error,
                    task.created_at,
                ),
            )

    def mark_task_submitted(self, task_id: str) -> None:
        self._update_task_state(task_id, "submitted", submitted_at=now_iso())

    def mark_task_completed(self, task_id: str) -> None:
        self._update_task_state(task_id, "done", completed_at=now_iso())

    def _update_task_state(self, task_id: str, state: str, **fields: Any) -> None:
        assignments = ["queue_state = ?"]
        values: list[Any] = [state]
        for key, value in fields.items():
            assignments.append(f"{key} = ?")
            values.append(value)
        values.append(task_id)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE tasks SET {', '.join(assignments)} WHERE task_id = ?",
                values,
            )

    def record_render(
        self,
        bvid: str,
        text_file: Path,
        markdown_file: Path | None,
        ai_provider: str | None,
        status: str,
        error: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO rendered_files (
                    bvid, text_file, markdown_file, ai_provider, render_status,
                    last_error, rendered_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bvid, text_file) DO UPDATE SET
                    markdown_file=excluded.markdown_file,
                    ai_provider=excluded.ai_provider,
                    render_status=excluded.render_status,
                    last_error=excluded.last_error,
                    rendered_at=excluded.rendered_at
                """,
                (
                    bvid,
                    str(text_file),
                    str(markdown_file) if markdown_file else None,
                    ai_provider,
                    status,
                    error,
                    now_iso(),
                ),
            )


def migrate_main_database(source_path: Path, target_path: Path, *, dry_run: bool = False) -> dict[str, int]:
    source_path = Path(source_path)
    target_path = Path(target_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"Source database does not exist: {source_path}")

    with sqlite3.connect(source_path) as source:
        source.row_factory = sqlite3.Row
        _validate_main_database(source)
        rows = source.execute(
            """
            SELECT bvid, up_name, up_mid, title, link, pubdate, duration, cid, status, timestamp
            FROM videos
            ORDER BY timestamp, bvid
            """
        ).fetchall()

    stats = {"read": len(rows), "inserted": 0, "updated": 0}
    if dry_run:
        return stats

    target = ClientDatabase(target_path)
    target.initialize()
    now = now_iso()
    with target.connect() as conn:
        for row in rows:
            bvid = str(row["bvid"])
            existed = conn.execute("SELECT 1 FROM videos WHERE bvid = ?", (bvid,)).fetchone() is not None
            seen_at = row["timestamp"] or now
            conn.execute(
                """
                INSERT INTO videos (
                    bvid, aid, cid, title, up_name, up_mid, pubdate, duration,
                    source_url, video_status, first_seen_at, last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bvid) DO UPDATE SET
                    cid=excluded.cid,
                    title=excluded.title,
                    up_name=excluded.up_name,
                    up_mid=excluded.up_mid,
                    pubdate=excluded.pubdate,
                    duration=excluded.duration,
                    source_url=excluded.source_url,
                    video_status=excluded.video_status,
                    last_seen_at=excluded.last_seen_at
                """,
                (
                    bvid,
                    None,
                    row["cid"],
                    str(row["title"] or ""),
                    str(row["up_name"] or ""),
                    row["up_mid"],
                    row["pubdate"],
                    int(row["duration"] or 0),
                    str(row["link"] or f"https://www.bilibili.com/video/{bvid}"),
                    str(row["status"] or "normal"),
                    seen_at,
                    seen_at,
                ),
            )
            if existed:
                stats["updated"] += 1
            else:
                stats["inserted"] += 1
    return stats


def _validate_main_database(conn: sqlite3.Connection) -> None:
    table = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'videos'").fetchone()
    if table is None:
        raise ValueError("Source database does not contain videos table")
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(videos)").fetchall()}
    missing = MAIN_VIDEO_COLUMNS - columns
    if missing:
        raise ValueError(f"Source videos table is missing columns: {', '.join(sorted(missing))}")
