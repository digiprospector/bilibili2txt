from __future__ import annotations

import logging
from argparse import Namespace
from pathlib import Path
import git

from bilibili2txt.commands import server as server_commands
from bilibili2txt.config import CommandContext, load_config
from bilibili2txt.models import Task
from bilibili2txt.services.gitqueue import GitQueue


def make_task(bvid: str, duration: int) -> Task:
    return Task(
        task_id=bvid,
        bvid=bvid,
        title=f"title-{bvid}",
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
                "server:",
                "  server_id: test-server",
                "  faster_whisper_path: .",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return CommandContext(load_config(config_path), "server")


def test_transcribe_skips_when_result_exists(tmp_path: Path, monkeypatch):
    ctx = _context(tmp_path)

    # Initialize fake git queue repo
    repo_dir = ctx.config.queue_dir
    repo_dir.mkdir(parents=True, exist_ok=True)
    git.Repo.init(repo_dir)

    queue = GitQueue(repo_dir, logging.getLogger("test"))
    queue.ensure_layout()

    # Add task and claim it
    task = make_task("BV1111111111", 100)
    task.mark_claimed("test-server")
    claimed_path = queue.claimed_dir / "test-server" / task.filename
    task.write_json(claimed_path)

    # Create the result directory with task.json to simulate a completed run
    result_dir = ctx.config.temp_dir / "server_results" / task.task_id
    result_dir.mkdir(parents=True, exist_ok=True)
    task.write_json(result_dir / "task.json")

    # We monkeypatch AudioService and Transcriber to make sure they are NOT called
    # If they are called, it would raise AssertionError
    def mock_audio_service(*args, **kwargs):
        raise AssertionError("AudioService should not be initialized when result exists")

    monkeypatch.setattr("bilibili2txt.commands.server.AudioService", mock_audio_service)

    args = Namespace(server_id="test-server")
    code = server_commands.transcribe(ctx, args, logging.getLogger("test"))

    assert code == 0


def test_once_returns_2_on_failure(tmp_path: Path, monkeypatch):
    ctx = _context(tmp_path)

    # Initialize fake git queue repo
    repo_dir = ctx.config.queue_dir
    repo_dir.mkdir(parents=True, exist_ok=True)
    git.Repo.init(repo_dir)

    queue = GitQueue(repo_dir, logging.getLogger("test"))
    queue.ensure_layout()

    # Add task and claim it
    task = make_task("BV2222222222", 100)
    task.mark_claimed("test-server")
    claimed_path = queue.claimed_dir / "test-server" / task.filename
    task.write_json(claimed_path)

    # Mock transcribe to return 1 (failure)
    monkeypatch.setattr("bilibili2txt.commands.server.transcribe", lambda *a, **k: 1)
    # Mock publish to return 1
    monkeypatch.setattr("bilibili2txt.commands.server.publish", lambda *a, **k: 1)

    args = Namespace(server_id="test-server", max_duration=864000)
    code = server_commands.once(ctx, args, logging.getLogger("test"), sync=False)

    assert code == 2


def test_run_continues_on_once_returning_2(tmp_path: Path, monkeypatch):
    ctx = _context(tmp_path)

    calls = []
    def mock_once(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            return 2  # task processing failed on first try
        return 1  # empty queue on second try

    monkeypatch.setattr("bilibili2txt.commands.server.once", mock_once)
    monkeypatch.setattr("bilibili2txt.commands.server.release_claimed", lambda *a, **k: 0)
    monkeypatch.setattr("bilibili2txt.commands.server.publish", lambda *a, **k: 1)
    monkeypatch.setattr("time.sleep", lambda seconds: None)  # avoid sleeping in tests

    args = Namespace(
        server_id="test-server",
        max_tasks=0,
        interval=5,
        claim_timeout_minutes=180,
        keep_local_result=False,
    )
    exit_code = server_commands.run(ctx, args, logging.getLogger("test"))

    assert len(calls) == 2
    assert exit_code == 1  # returns 1 because had_failure was set to True

