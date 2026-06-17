from __future__ import annotations

import logging
from argparse import Namespace
from pathlib import Path

import git

from bilibili2txt.commands.client import prepare_audio
from bilibili2txt.config import CommandContext, load_config
from bilibili2txt.models import Task
from bilibili2txt.services.gitqueue import GitQueue
from bilibili2txt.services.audio import AudioService
from bilibili2txt.services.webdav import WebDavClient


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
                "client:",
                "  local_download_audio_seconds: 100",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return CommandContext(load_config(config_path), "client prepare-audio")


def test_prepare_audio_scans_temp_and_queue_pending(tmp_path: Path, monkeypatch):
    ctx = _context(tmp_path)
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    git.Repo.init(queue_dir)
    queue = GitQueue(queue_dir, logging.getLogger("test"))
    queue.ensure_layout()

    # Mocks
    sync_called = False
    def mock_sync(self):
        nonlocal sync_called
        sync_called = True

    monkeypatch.setattr(GitQueue, "sync", mock_sync)

    downloaded_bvids = []
    uploaded_bvids = []
    
    def mock_download_task_audio(self, task: Task):
        downloaded_bvids.append(task.bvid)
        return ["dummy.mp3"]

    def mock_upload_task_audio(self, task: Task, files):
        uploaded_bvids.append(task.bvid)
        return True

    monkeypatch.setattr(AudioService, "download_task_audio", mock_download_task_audio)
    monkeypatch.setattr(AudioService, "upload_task_audio", mock_upload_task_audio)

    # Mock WebDAV listing to have one of the tasks already processed
    monkeypatch.setattr(WebDavClient, "from_config", classmethod(lambda cls, config, logger: WebDavClient(
        base_url="http://dummy", username="user", password="pwd", logger=logger
    )))
    monkeypatch.setattr(WebDavClient, "list_files", lambda self: {"already_done.mp3"})

    temp_tasks_dir = tmp_path / "temp" / "tasks"
    temp_tasks_dir.mkdir(parents=True, exist_ok=True)

    # 1. Normal task in temp/tasks (duration = 150 > min_duration 100)
    task1 = Task(
        task_id="BVtemp",
        bvid="BVtemp",
        title="temp title",
        up_name="up",
        up_mid=1,
        pubdate=1718500000,
        duration=150,
        cid=1,
        status="normal",
        source_url="https://www.bilibili.com/video/BVtemp",
        created_at="2026-06-16T10:00:00+08:00",
    )
    task1_path = temp_tasks_dir / "000150_20260616T100000_BVtemp.json"
    task1.write_json(task1_path)

    # 2. Too short task in temp/tasks (duration = 50 <= min_duration 100)
    task2 = Task(
        task_id="BVshort",
        bvid="BVshort",
        title="short title",
        up_name="up",
        up_mid=1,
        pubdate=1718500000,
        duration=50,
        cid=2,
        status="normal",
        source_url="https://www.bilibili.com/video/BVshort",
        created_at="2026-06-16T10:00:00+08:00",
    )
    task2_path = temp_tasks_dir / "000050_20260616T100000_BVshort.json"
    task2.write_json(task2_path)

    # 3. Already uploaded task in temp/tasks
    task3 = Task(
        task_id="BValready_done",
        bvid="already_done",
        title="already done title",
        up_name="up",
        up_mid=1,
        pubdate=1718500000,
        duration=200,
        cid=3,
        status="normal",
        source_url="https://www.bilibili.com/video/already_done",
        created_at="2026-06-16T10:00:00+08:00",
    )
    task3_path = temp_tasks_dir / "000200_20260616T100000_BValready_done.json"
    task3.write_json(task3_path)

    # 4. Normal task in queue/pending
    task4 = Task(
        task_id="BVpending",
        bvid="BVpending",
        title="pending title",
        up_name="up",
        up_mid=1,
        pubdate=1718500000,
        duration=300,
        cid=4,
        status="normal",
        source_url="https://www.bilibili.com/video/BVpending",
        created_at="2026-06-16T10:00:00+08:00",
    )
    task4_path = queue.pending_dir / "000300_20260616T100000_BVpending.json"
    queue.ensure_layout()
    task4.write_json(task4_path)

    # Run prepare-audio
    args = Namespace(min_duration=None)
    code = prepare_audio(ctx, args, logging.getLogger("test"))

    assert code == 0
    assert sync_called

    # Verify task1 and task4 were downloaded & uploaded
    assert "BVtemp" in downloaded_bvids
    assert "BVpending" in downloaded_bvids
    assert "BVtemp" in uploaded_bvids
    assert "BVpending" in uploaded_bvids

    # Verify task2 (short) and task3 (already done) were skipped
    assert "BVshort" not in downloaded_bvids
    assert "already_done" not in downloaded_bvids

    # Verify no files were deleted or moved (as per "不移动" and normal client behavior)
    assert task1_path.exists()
    assert task2_path.exists()
    assert task3_path.exists()
    assert task4_path.exists()
