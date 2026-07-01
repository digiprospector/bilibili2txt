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


def test_collect_cleans_up_already_collected_results(tmp_path: Path, monkeypatch):
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

    # Pre-create the saved transcript in save_dir so collect skips copying but deletes from queue
    save_dir = data_dir / "save"
    save_dir.mkdir(parents=True)
    from bilibili2txt.commands.client import _final_transcript_name
    target = save_dir / _final_transcript_name(task, result_dir / "transcript_1.text")
    target.write_text("transcript", encoding="utf-8")

    ctx = CommandContext(load_config(config_path), "client collect")
    monkeypatch.setattr(CommandContext, "queue", lambda _self, _logger, **_kw: queue)
    monkeypatch.setattr(CommandContext, "database", lambda _self: _make_db(data_dir))
    code = collect(ctx, Namespace(force=False), logging.getLogger("test"))

    assert code == 0
    # The result directory should be deleted from results and not exist in done
    assert not result_dir.exists()
    assert not (queue.done_dir / task.task_id).exists()

    # We should still have the saved file in save_dir
    assert target.exists()


def test_collect_cleans_up_leftover_done_directories_when_already_collected(tmp_path: Path, monkeypatch):
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

    # 1. Simulate a leftover task directory inside done_dir (queue/done/task_id)
    leftover_done_dir = queue.done_dir / task.task_id
    leftover_done_dir.mkdir(parents=True)
    task.write_json(leftover_done_dir / "task.json")

    # 2. Simulate that this task is already collected in data/save
    save_dir = data_dir / "save"
    save_dir.mkdir(parents=True)
    (save_dir / f"[2026-06-16_10-00-00][up][title][{task.bvid}].text").write_text("transcript", encoding="utf-8")

    ctx = CommandContext(load_config(config_path), "client collect")
    monkeypatch.setattr(CommandContext, "queue", lambda _self, _logger, **_kw: queue)
    monkeypatch.setattr(CommandContext, "database", lambda _self: _make_db(data_dir))
    code = collect(ctx, Namespace(force=False), logging.getLogger("test"))

    assert code == 0
    # The leftover done directory should be cleaned up!
    assert not leftover_done_dir.exists()


def test_resubmit_missing_cleans_up_failed_directory(tmp_path: Path, monkeypatch):
    from bilibili2txt.commands.client import resubmit_missing
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

    # Place task JSON under failed directory
    failed_task_dir = queue.failed_dir / task.task_id
    failed_task_dir.mkdir(parents=True)
    failed_task_file = failed_task_dir / "task.json"
    task.write_json(failed_task_file)

    ctx = CommandContext(load_config(config_path), "client resubmit-missing")
    monkeypatch.setattr(CommandContext, "queue", lambda _self, _logger, **_kw: queue)
    monkeypatch.setattr(CommandContext, "database", lambda _self: _make_db(data_dir))

    # Test 1: Successful resubmit should delete failed directory
    code = resubmit_missing(ctx, Namespace(input=str(failed_task_file)), logging.getLogger("test"))
    assert code == 0
    assert not failed_task_dir.exists()
    assert (queue.pending_dir / task.filename).exists()

    # Recreate failed directory for the next test
    failed_task_dir.mkdir(parents=True)
    task.write_json(failed_task_file)

    # Test 2: Skipping resubmit (since it's already in pending) should still clean up the failed directory
    code = resubmit_missing(ctx, Namespace(input=str(failed_task_file)), logging.getLogger("test"))
    assert code == 0
    assert not failed_task_dir.exists()


def test_resubmit_missing_with_failed_and_exclude(tmp_path: Path, monkeypatch):
    from bilibili2txt.commands.client import resubmit_missing
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

    def local_make_task(bvid: str, duration: int, title: str) -> Task:
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

    task1 = local_make_task("BVfailed1", 100, "Failed 1")
    task2 = local_make_task("BVfailed2", 200, "Failed 2")

    # Place task1 JSON under failed directory
    failed_dir1 = queue.failed_dir / task1.task_id
    failed_dir1.mkdir(parents=True)
    task1.write_json(failed_dir1 / "task.json")

    # Place task2 JSON under failed directory
    failed_dir2 = queue.failed_dir / task2.task_id
    failed_dir2.mkdir(parents=True)
    task2.write_json(failed_dir2 / "task.json")

    ctx = CommandContext(load_config(config_path), "client resubmit-missing")
    monkeypatch.setattr(CommandContext, "queue", lambda _self, _logger, **_kw: queue)
    monkeypatch.setattr(CommandContext, "database", lambda _self: _make_db(data_dir))

    # Resubmit failed tasks but exclude BVfailed1
    args = Namespace(input=None, failed=True, exclude=["BVfailed1"])
    code = resubmit_missing(ctx, args, logging.getLogger("test"))
    assert code == 0

    # BVfailed1 should be excluded (still in failed directory, not in pending)
    assert failed_dir1.exists()
    assert not (queue.pending_dir / task1.filename).exists()

    # BVfailed2 should be resubmitted (removed from failed, exists in pending)
    assert not failed_dir2.exists()
    assert (queue.pending_dir / task2.filename).exists()
