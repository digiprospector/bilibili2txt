from __future__ import annotations

import logging
from argparse import Namespace
from pathlib import Path

from bilibili2txt.commands import admin as admin_commands
from bilibili2txt.config import CommandContext, load_config
from bilibili2txt.database import ClientDatabase


def _context(tmp_path: Path) -> CommandContext:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "app:",
                f"  temp_dir: {(tmp_path / 'temp').as_posix()}",
                f"  logs_dir: {(tmp_path / 'logs').as_posix()}",
                "data:",
                f"  repo_dir: {(tmp_path / 'data').as_posix()}",
                "queue:",
                f"  repo_dir: {(tmp_path / 'queue').as_posix()}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return CommandContext(load_config(config_path), "admin")


def _create_main_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = ClientDatabase(path)
    with db.connect() as conn:
        conn.executescript(
            """
            CREATE TABLE videos (
                bvid TEXT PRIMARY KEY,
                up_name TEXT NOT NULL,
                up_mid INTEGER NOT NULL,
                title TEXT NOT NULL,
                link TEXT NOT NULL,
                pubdate INTEGER,
                duration INTEGER,
                cid INTEGER,
                status TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO videos (bvid, up_name, up_mid, title, link, pubdate, duration, cid, status, timestamp)
            VALUES
                ('BV1abc', 'UP A', 1001, 'Old title', 'https://www.bilibili.com/video/BV1abc', 1718500000, 321, 11, 'normal', '2026-06-16T10:00:00+08:00'),
                ('BV2def', 'UP B', 1002, 'Another title', 'https://www.bilibili.com/video/BV2def', NULL, NULL, NULL, NULL, NULL);
            """
        )


def test_migrate_main_db_copies_rows_into_dev_schema(tmp_path: Path):
    ctx = _context(tmp_path)
    source = tmp_path / "main.db"
    target = tmp_path / "dev.db"
    _create_main_db(source)

    code = admin_commands.migrate_main_db(
        ctx,
        Namespace(source_db=source, target_db=target, dry_run=False),
        logging.getLogger("test"),
    )

    assert code == 0
    db = ClientDatabase(target)
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM videos ORDER BY bvid").fetchall()

    assert len(rows) == 2
    assert rows[0]["bvid"] == "BV1abc"
    assert rows[0]["source_url"] == "https://www.bilibili.com/video/BV1abc"
    assert rows[0]["video_status"] == "normal"
    assert rows[0]["first_seen_at"] == "2026-06-16T10:00:00+08:00"
    assert rows[0]["last_seen_at"] == "2026-06-16T10:00:00+08:00"
    assert rows[1]["video_status"] == "normal"
    assert rows[1]["duration"] == 0


def test_migrate_main_db_dry_run_does_not_write_target(tmp_path: Path):
    ctx = _context(tmp_path)
    source = tmp_path / "main.db"
    target = tmp_path / "dev.db"
    _create_main_db(source)

    code = admin_commands.migrate_main_db(
        ctx,
        Namespace(source_db=source, target_db=target, dry_run=True),
        logging.getLogger("test"),
    )

    assert code == 0
    assert not target.exists()
