from __future__ import annotations

import logging
from argparse import Namespace
from pathlib import Path

import git

from bilibili2txt.commands.client import collect
from bilibili2txt.config import CommandContext, load_config
from bilibili2txt.database import ClientDatabase
from bilibili2txt.models import Task
from bilibili2txt.services.gitqueue import GitQueue


def _make_db(data_dir: Path) -> ClientDatabase:
    db = ClientDatabase(data_dir / "bilibili2txt.db")
    db.initialize()
    return db


def _make_task() -> Task:
    return Task(
        task_id="BVcollect",
        bvid="BVcollect",
        title="title",
        up_name="up",
        up_mid=1,
        pubdate=1718500000,
        duration=123,
        cid=1,
        status="normal",
        source_url="https://www.bilibili.com/video/BVcollect",
        created_at="2026-06-16T10:00:00+08:00",
    )


def test_collect_copies_transcript_moves_result_and_deletes_missing(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    queue_dir = tmp_path / "queue"
    temp_dir = tmp_path / "temp"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "app:",
                f"  temp_dir: {temp_dir.as_posix()}",
                "  logs_dir: logs",
                "data:",
                f"  repo_dir: {data_dir.as_posix()}",
                "queue:",
                f"  repo_dir: {queue_dir.as_posix()}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    queue_dir.mkdir()
    git.Repo.init(queue_dir)
    queue = GitQueue(queue_dir, logging.getLogger("test"))
    queue.ensure_layout()
    monkeypatch.setattr(queue, "sync", lambda: None)
    monkeypatch.setattr(queue, "commit_and_push", lambda _message: None)

    task = _make_task()
    result_dir = queue.results_dir / task.task_id
    result_dir.mkdir(parents=True)
    task.write_json(result_dir / "task.json")
    (result_dir / "transcript_1.text").write_text("transcript", encoding="utf-8")
    missing_dir = temp_dir / "missing_tasks"
    missing_dir.mkdir(parents=True)
    task.write_json(missing_dir / "missing.json")

    submitted_dir = data_dir / "tasks" / "submitted"
    submitted_dir.mkdir(parents=True)
    task.write_json(submitted_dir / "submitted_task.json")

    ctx = CommandContext(load_config(config_path), "client collect")
    monkeypatch.setattr(CommandContext, "queue", lambda _self, _logger, **_kw: queue)
    monkeypatch.setattr(CommandContext, "database", lambda _self: _make_db(data_dir))
    code = collect(ctx, Namespace(force=False), logging.getLogger("test"))

    assert code == 0
    assert not result_dir.exists()
    assert not (queue.done_dir / task.task_id).exists()
    assert not (missing_dir / "missing.json").exists()
    assert not (submitted_dir / "submitted_task.json").exists()
    saved = list((data_dir / "save").glob("*.text"))
    assert len(saved) == 1
