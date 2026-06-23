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


def test_prepare_audio_retries_failed_yt_dlp_tasks(tmp_path: Path, monkeypatch):
    ctx = _context(tmp_path)
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    git.Repo.init(queue_dir)
    queue = GitQueue(queue_dir, logging.getLogger("test"))
    queue.ensure_layout()

    # Mocks
    monkeypatch.setattr(GitQueue, "sync", lambda self: None)
    
    commit_push_called = []
    def mock_commit_and_push(self, msg: str):
        commit_push_called.append(msg)
    monkeypatch.setattr(GitQueue, "commit_and_push", mock_commit_and_push)

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

    # WebDAV listing mock
    monkeypatch.setattr(WebDavClient, "from_config", classmethod(lambda cls, config, logger: WebDavClient(
        base_url="http://dummy", username="user", password="pwd", logger=logger
    )))
    monkeypatch.setattr(WebDavClient, "list_files", lambda self: {"BVwebdav.mp3"})

    failed_dir = queue.failed_dir

    # 1. Failed task due to yt-dlp, should be retried and moved to pending
    task_ytdlp = Task(
        task_id="BVytdlp",
        bvid="BVytdlp",
        title="ytdlp title",
        up_name="up",
        up_mid=1,
        pubdate=1718500000,
        duration=200,
        cid=10,
        status="normal",
        source_url="https://www.bilibili.com/video/BVytdlp",
        created_at="2026-06-16T10:00:00+08:00",
        attempts=3,
        last_error="yt-dlp 下载失败: Test Error",
        client_retries=0,
    )
    task_ytdlp_dir = failed_dir / "BVytdlp"
    task_ytdlp_dir.mkdir(parents=True, exist_ok=True)
    task_ytdlp_path = task_ytdlp_dir / "task.json"
    task_ytdlp.write_json(task_ytdlp_path)

    # 2. Failed task due to other errors, should be skipped
    task_other = Task(
        task_id="BVother",
        bvid="BVother",
        title="other title",
        up_name="up",
        up_mid=1,
        pubdate=1718500000,
        duration=200,
        cid=11,
        status="normal",
        source_url="https://www.bilibili.com/video/BVother",
        created_at="2026-06-16T10:00:00+08:00",
        attempts=3,
        last_error="Whisper failed to run",
        client_retries=0,
    )
    task_other_dir = failed_dir / "BVother"
    task_other_dir.mkdir(parents=True, exist_ok=True)
    task_other_path = task_other_dir / "task.json"
    task_other.write_json(task_other_path)

    # 3. Failed task due to yt-dlp but already retried 3 times, should be skipped
    task_max = Task(
        task_id="BVmax",
        bvid="BVmax",
        title="max title",
        up_name="up",
        up_mid=1,
        pubdate=1718500000,
        duration=200,
        cid=12,
        status="normal",
        source_url="https://www.bilibili.com/video/BVmax",
        created_at="2026-06-16T10:00:00+08:00",
        attempts=3,
        last_error="yt-dlp 下载失败: Test Error",
        client_retries=3,
    )
    task_max_dir = failed_dir / "BVmax"
    task_max_dir.mkdir(parents=True, exist_ok=True)
    task_max_path = task_max_dir / "task.json"
    task_max.write_json(task_max_path)

    # 4. Failed task due to yt-dlp, but audio is already on WebDAV, should be moved to pending directly
    task_webdav = Task(
        task_id="BVwebdav",
        bvid="BVwebdav",
        title="webdav title",
        up_name="up",
        up_mid=1,
        pubdate=1718500000,
        duration=200,
        cid=13,
        status="normal",
        source_url="https://www.bilibili.com/video/BVwebdav",
        created_at="2026-06-16T10:00:00+08:00",
        attempts=3,
        last_error="yt-dlp 下载失败: Test Error",
        client_retries=0,
    )
    task_webdav_dir = failed_dir / "BVwebdav"
    task_webdav_dir.mkdir(parents=True, exist_ok=True)
    task_webdav_path = task_webdav_dir / "task.json"
    task_webdav.write_json(task_webdav_path)

    # Run prepare-audio
    args = Namespace(min_duration=None)
    code = prepare_audio(ctx, args, logging.getLogger("test"))

    assert code == 0

    # Verify BVytdlp was downloaded & uploaded
    assert "BVytdlp" in downloaded_bvids
    assert "BVytdlp" in uploaded_bvids

    # Verify BVwebdav was NOT downloaded (directly moved to pending)
    assert "BVwebdav" not in downloaded_bvids

    # Verify BVother and BVmax were NOT downloaded
    assert "BVother" not in downloaded_bvids
    assert "BVmax" not in downloaded_bvids

    # Verify files in failed queue
    assert not task_ytdlp_path.exists()
    assert not task_ytdlp_dir.exists()
    assert not task_webdav_path.exists()
    assert not task_webdav_dir.exists()

    assert task_other_path.exists()
    assert task_max_path.exists()

    # Verify files in pending queue
    pending_files = list(queue.pending_dir.glob("*.json"))
    pending_task_ids = {Task.from_file(p).task_id for p in pending_files}
    assert "BVytdlp" in pending_task_ids
    assert "BVwebdav" in pending_task_ids

    # Verify attempts and client_retries in pending queue are reset
    ytdlp_pending = next(p for p in pending_files if "BVytdlp" in p.name)
    ytdlp_task = Task.from_file(ytdlp_pending)
    assert ytdlp_task.attempts == 0
    assert ytdlp_task.client_retries == 0
    assert ytdlp_task.last_error is None

    # Verify commit_and_push was called
    assert len(commit_push_called) > 0

