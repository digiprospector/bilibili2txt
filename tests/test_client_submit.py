from __future__ import annotations

import logging
from argparse import Namespace
from pathlib import Path

import git

from bilibili2txt.commands.client import submit
from bilibili2txt.config import CommandContext, load_config
from bilibili2txt.database import ClientDatabase
from bilibili2txt.models import Task
from bilibili2txt.services.gitqueue import GitQueue


def _make_db(data_dir: Path) -> ClientDatabase:
    db = ClientDatabase(data_dir / "bilibili2txt.db")
    db.initialize()
    return db


def _context(tmp_path: Path) -> CommandContext:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "app:",
                f"  temp_dir: {(tmp_path / 'temp').as_posix()}",
                "  logs_dir: logs",
                "data:",
                f"  repo_dir: {(tmp_path / 'data').as_posix()}",
                "queue:",
                f"  repo_dir: {(tmp_path / 'queue').as_posix()}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return CommandContext(load_config(config_path), "client submit")


def test_submit_deletes_skipped_tasks(tmp_path: Path, monkeypatch):
    ctx = _context(tmp_path)
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    git.Repo.init(queue_dir)
    queue = GitQueue(queue_dir, logging.getLogger("test"))
    queue.ensure_layout()
    
    # Mock git operations
    monkeypatch.setattr(queue, "sync", lambda: None)
    monkeypatch.setattr(queue, "commit_and_push", lambda _message: None)
    monkeypatch.setattr(CommandContext, "queue", lambda _self, _logger, **_kw: queue)
    monkeypatch.setattr(CommandContext, "database", lambda _self: _make_db(tmp_path / "data"))

    temp_tasks_dir = tmp_path / "temp" / "tasks"
    temp_tasks_dir.mkdir(parents=True, exist_ok=True)

    # 1. Normal task (should be moved to submitted)
    normal_task = Task(
        task_id="BVnormal",
        bvid="BVnormal",
        title="normal title",
        up_name="up",
        up_mid=1,
        pubdate=1718500000,
        duration=100,
        cid=1,
        status="normal",
        source_url="https://www.bilibili.com/video/BVnormal",
        created_at="2026-06-16T10:00:00+08:00",
    )
    normal_path = temp_tasks_dir / "000100_20260616T100000_BVnormal.json"
    normal_task.write_json(normal_path)

    # 2. Too long task (status != "normal", should be deleted)
    long_task = Task(
        task_id="BVlong",
        bvid="BVlong",
        title="long title",
        up_name="up",
        up_mid=1,
        pubdate=1718500000,
        duration=10000,
        cid=2,
        status="too_long",
        source_url="https://www.bilibili.com/video/BVlong",
        created_at="2026-06-16T10:00:00+08:00",
    )
    long_path = temp_tasks_dir / "010000_20260616T100000_BVlong.json"
    long_task.write_json(long_path)

    # 3. Duplicate task (already in queue, should be deleted)
    dup_task = Task(
        task_id="BVdup",
        bvid="BVdup",
        title="dup title",
        up_name="up",
        up_mid=1,
        pubdate=1718500000,
        duration=200,
        cid=3,
        status="normal",
        source_url="https://www.bilibili.com/video/BVdup",
        created_at="2026-06-16T10:00:00+08:00",
    )
    queue.add_pending_task(dup_task)
    dup_path = temp_tasks_dir / "000200_20260616T100000_BVdup.json"
    dup_task.write_json(dup_path)

    # 4. Invalid task file (malformed JSON, should be deleted)
    invalid_path = temp_tasks_dir / "invalid.json"
    invalid_path.write_text("malformed json text", encoding="utf-8")

    code = submit(ctx, Namespace(input=None), logging.getLogger("test"))

    # The command should succeed since only invalid task raises failed status code,
    # wait: code is 0 if failed == 0 else 1. Here we have 1 invalid file (failed = 1), so code should be 1.
    assert code == 1

    # Verify normal task was submitted (moved to submitted directory)
    assert not normal_path.exists()
    assert (tmp_path / "data" / "tasks" / "submitted" / normal_path.name).exists()
    assert queue.task_exists("BVnormal")

    # Verify skipped tasks (too long and duplicate) and invalid file were deleted
    assert not long_path.exists()
    assert not dup_path.exists()
    assert not invalid_path.exists()
