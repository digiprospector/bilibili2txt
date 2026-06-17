from __future__ import annotations

import logging
from argparse import Namespace
from pathlib import Path

from bilibili2txt.commands import client as client_commands
from bilibili2txt.config import CommandContext, load_config
from bilibili2txt.database import ClientDatabase
from bilibili2txt.models import Task


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
    return CommandContext(load_config(config_path), "client scan")


class FakeBilibiliService:
    def __init__(self, _config, _logger):
        pass

    def login(self) -> bool:
        return True

    def iter_target_videos(self, _up_mid, *, groups=None, max_pages=1):
        yield {
            "bvid": "BVexisting",
            "title": "existing",
            "up_name": "up",
            "up_mid": 1,
            "source_url": "https://www.bilibili.com/video/BVexisting",
        }

    def get_video_detail(self, bvid: str | None = None, aid: int | None = None):
        raise AssertionError(f"Unexpected detail request for existing video: {bvid or aid}")


def test_scan_skips_existing_video_without_fetching_detail(tmp_path: Path, monkeypatch):
    ctx = _context(tmp_path)
    db = ClientDatabase(ctx.db_path)
    db.initialize()
    db.upsert_video(
        Task(
            task_id="BVexisting",
            bvid="BVexisting",
            title="existing",
            up_name="up",
            up_mid=1,
            pubdate=1718500000,
            duration=123,
            cid=1,
            status="normal",
            source_url="https://www.bilibili.com/video/BVexisting",
            created_at="2026-06-16T10:00:00+08:00",
        )
    )
    monkeypatch.setattr(client_commands, "BilibiliService", FakeBilibiliService)

    code = client_commands.scan(
        ctx,
        Namespace(up_mid=None, group=None, max_pages=None),
        logging.getLogger("test"),
    )

    assert code == 0
    assert not list((ctx.config.temp_dir / "tasks").glob("*.json"))


class FakeNewBilibiliService:
    def __init__(self, _config, _logger):
        pass

    def login(self) -> bool:
        return True

    def iter_target_videos(self, _up_mid, *, groups=None, max_pages=1):
        yield {
            "bvid": "BVnew",
            "title": "new video",
            "up_name": "up",
            "up_mid": 1,
            "source_url": "https://www.bilibili.com/video/BVnew",
        }

    def get_video_detail(self, bvid: str | None = None, aid: int | None = None):
        return {
            "pubdate": 1718500000,
            "duration": 200,
            "cid": 2,
        }


def test_scan_deletes_previous_task_file_with_same_bvid(tmp_path: Path, monkeypatch):
    ctx = _context(tmp_path)
    db = ClientDatabase(ctx.db_path)
    db.initialize()

    # Pre-create an old task file in temp/tasks for "BVnew" with a different timestamp/duration
    tasks_dir = ctx.config.temp_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    old_file = tasks_dir / "000123_20260616T000000_BVnew.json"
    old_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(client_commands, "BilibiliService", FakeNewBilibiliService)

    code = client_commands.scan(
        ctx,
        Namespace(up_mid=None, group=None, max_pages=None),
        logging.getLogger("test"),
    )

    assert code == 0
    # The old file should have been deleted
    assert not old_file.exists()
    # There should be exactly one JSON file now, representing the newly scanned task
    scanned_files = list(tasks_dir.glob("*.json"))
    assert len(scanned_files) == 1
    assert scanned_files[0].name.endswith("_BVnew.json")
    assert scanned_files[0].name != "000123_20260616T000000_BVnew.json"
