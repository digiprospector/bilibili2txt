from __future__ import annotations

from pathlib import Path

from bilibili2txt.config import ConfigError, load_config
from bilibili2txt.database import ClientDatabase
from bilibili2txt.models import Task


def test_load_config_prefers_explicit_path(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "custom.yaml"
    temp_dir = tmp_path / "custom-temp"
    queue_dir = tmp_path / "custom-queue"
    cfg.write_text(
        f"app:\n  temp_dir: {temp_dir.as_posix()}\nqueue:\n  repo_dir: {queue_dir.as_posix()}\n",
        encoding="utf-8",
    )

    config = load_config(cfg)

    assert config.config_path == cfg
    assert config.temp_dir == temp_dir
    assert config.queue_dir == queue_dir


def test_load_config_rejects_missing_path(tmp_path: Path):
    missing = tmp_path / "missing.yaml"

    try:
        load_config(missing)
    except ConfigError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("Expected ConfigError")


def test_task_filename_is_stable():
    task = Task(
        task_id="BV1abc",
        bvid="BV1abc",
        title="title",
        up_name="up",
        up_mid=1,
        pubdate=1718500000,
        duration=123,
        cid=1,
        status="normal",
        source_url="https://www.bilibili.com/video/BV1abc",
        created_at="2026-06-16T10:00:00+08:00",
    )

    assert task.filename == "000123_20260616T100000_BV1abc.json"


def test_database_initialize_and_upsert(tmp_path: Path):
    db_path = tmp_path / "data" / "bilibili2txt.db"
    db = ClientDatabase(db_path)
    db.initialize()
    task = Task(
        task_id="BV1abc",
        bvid="BV1abc",
        title="title",
        up_name="up",
        up_mid=1,
        pubdate=1718500000,
        duration=123,
        cid=1,
        status="normal",
        source_url="https://www.bilibili.com/video/BV1abc",
        created_at="2026-06-16T10:00:00+08:00",
    )

    db.upsert_video(task)
    db.upsert_task(task, tmp_path / "task.json", "submitted")

    with db.connect() as conn:
        video = conn.execute("SELECT * FROM videos WHERE bvid = ?", (task.bvid,)).fetchone()
        task_row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task.task_id,)).fetchone()

    assert video["title"] == "title"
    assert task_row["queue_state"] == "submitted"
