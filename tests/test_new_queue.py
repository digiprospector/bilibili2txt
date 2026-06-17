from pathlib import Path
import logging

import git

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


def test_claim_longest_task(tmp_path: Path):
    repo_dir = tmp_path / "queue"
    repo_dir.mkdir()
    git.Repo.init(repo_dir)
    queue = GitQueue(repo_dir, logging.getLogger("test"))
    queue.ensure_layout()

    queue.add_pending_task(make_task("BV1111111111", 100))
    queue.add_pending_task(make_task("BV2222222222", 500))
    queue.add_pending_task(make_task("BV3333333333", 300))

    claimed = queue.claim_longest_task("server-a", 1000)

    assert claimed is not None
    path, task = claimed
    assert task.bvid == "BV2222222222"
    assert path.parent.name == "server-a"
    assert not any("BV2222222222" in p.name for p in queue.pending_dir.glob("*.json"))


def test_claim_resumes_existing_before_pending(tmp_path: Path):
    repo_dir = tmp_path / "queue"
    repo_dir.mkdir()
    git.Repo.init(repo_dir)
    queue = GitQueue(repo_dir, logging.getLogger("test"))
    queue.ensure_layout()

    existing = make_task("BVexisting", 100)
    existing.mark_claimed("server-a")
    existing.write_json(queue.claimed_dir / "server-a" / existing.filename)
    queue.add_pending_task(make_task("BVpending", 900))

    claimed = queue.claim_longest_task("server-a", 1000)

    assert claimed is not None
    path, task = claimed
    assert task.bvid == "BVexisting"
    assert path.parent.name == "server-a"
    assert any("BVpending" in p.name for p in queue.pending_dir.glob("*.json"))


def test_return_to_pending_removes_claim(tmp_path: Path):
    repo_dir = tmp_path / "queue"
    repo_dir.mkdir()
    git.Repo.init(repo_dir)
    queue = GitQueue(repo_dir, logging.getLogger("test"))
    queue.ensure_layout()
    queue.add_pending_task(make_task("BV1111111111", 100))
    claimed_path, task = queue.claim_longest_task("server-a", 1000)

    pending_path = queue.return_to_pending(claimed_path, task, "download failed")
    restored = Task.from_file(pending_path)

    assert pending_path.parent == queue.pending_dir
    assert not claimed_path.exists()
    assert restored.claimed_by is None
    assert restored.last_error == "download failed"


def test_commit_and_push_reports_missing_origin(tmp_path: Path):
    repo_dir = tmp_path / "queue"
    repo_dir.mkdir()
    git.Repo.init(repo_dir)
    queue = GitQueue(repo_dir, logging.getLogger("test"))
    queue.ensure_layout()

    try:
        queue.commit_and_push("test")
    except Exception as exc:
        assert "origin" in str(exc)
    else:
        raise AssertionError("Expected missing origin error")
