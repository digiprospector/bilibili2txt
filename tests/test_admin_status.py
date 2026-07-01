from __future__ import annotations

import logging
from argparse import Namespace
from pathlib import Path
import git

from bilibili2txt.commands import admin as admin_commands
from bilibili2txt.config import CommandContext, load_config
from bilibili2txt.models import Task
from bilibili2txt.services.gitqueue import GitQueue


def make_task(bvid: str, duration: int, title: str = "title") -> Task:
    return Task(
        task_id=bvid,
        bvid=bvid,
        title=title,
        up_name="up",
        up_mid=1,
        pubdate=1718500000,
        duration=duration,
        cid=1,
        status="normal",
        source_url=f"https://www.bilibili.com/video/{bvid}",
        created_at="2026-06-16T10:00:00+08:00",
    )


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


def test_admin_status_empty_queue(tmp_path: Path, monkeypatch):
    ctx = _context(tmp_path)

    # Initialize fake git queue repo
    repo_dir = ctx.config.queue_dir
    repo_dir.mkdir(parents=True, exist_ok=True)
    git.Repo.init(repo_dir)

    monkeypatch.setattr(GitQueue, "sync", lambda *args, **kwargs: None)

    args = Namespace(limit=10)
    code = admin_commands.status(ctx, args, logging.getLogger("test"))
    assert code == 0


def test_admin_status_with_tasks(tmp_path: Path, monkeypatch, capsys):
    ctx = _context(tmp_path)

    repo_dir = ctx.config.queue_dir
    repo_dir.mkdir(parents=True, exist_ok=True)
    git.Repo.init(repo_dir)

    monkeypatch.setattr(GitQueue, "sync", lambda *args, **kwargs: None)

    queue = GitQueue(repo_dir, logging.getLogger("test"))
    queue.ensure_layout()

    # 1. Add pending task
    task_pending = make_task("BVpending", 120, "Pending Video")
    queue.add_pending_task(task_pending)

    # 2. Add claimed task
    task_claimed = make_task("BVclaimed", 300, "Claimed Video")
    task_claimed.mark_claimed("server-a")
    claimed_path = queue.claimed_dir / "server-a" / task_claimed.filename
    task_claimed.write_json(claimed_path)

    # 3. Add results task
    task_result = make_task("BVresult", 60, "Result Video")
    result_dir = queue.results_dir / task_result.task_id
    result_dir.mkdir(parents=True, exist_ok=True)
    task_result.write_json(result_dir / "task.json")

    # 4. Add done task
    task_done = make_task("BVdone", 90, "Done Video")
    done_dir = queue.done_dir / task_done.task_id
    done_dir.mkdir(parents=True, exist_ok=True)
    task_done.write_json(done_dir / "task.json")

    # 5. Add failed task (download failure)
    task_failed = make_task("BVfailed", 200, "Failed Video")
    task_failed.mark_failed("yt-dlp error", "server-a")
    failed_dir = queue.failed_dir / task_failed.task_id
    failed_dir.mkdir(parents=True, exist_ok=True)
    task_failed.write_json(failed_dir / "task.json")

    args = Namespace(limit=2)
    code = admin_commands.status(ctx, args, logging.getLogger("test"))
    assert code == 0

    captured = capsys.readouterr().out

    # Verify counts in table
    assert "pending" in captured
    assert "claimed" in captured
    assert "results" in captured
    assert "done" in captured
    assert "failed" in captured

    # Verify table and details output content
    assert "Pending Video" in captured
    assert "Claimed Video" in captured
    assert "Result Video" in captured
    assert "Done Video" in captured
    assert "Failed Video" in captured

    # Verify recommended commands are outputted
    assert "Recommended Commands" in captured
    assert "python b2t.py server once" in captured
    assert "python b2t.py server release-claimed" in captured
    assert "python b2t.py client collect" in captured
    assert "python b2t.py client prepare-audio" in captured
