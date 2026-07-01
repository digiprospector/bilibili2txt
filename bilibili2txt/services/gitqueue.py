from __future__ import annotations

import logging
import shutil
from pathlib import Path

import git

from ..models import Task, now_iso
from .git_helpers import open_repo, commit_all, push_and_check


QUEUE_DIRS = ("pending", "claimed", "results", "done", "failed")


class QueueError(RuntimeError):
    pass


class GitQueue:
    def __init__(self, repo_dir: Path, logger: logging.Logger):
        self.repo_dir = repo_dir
        self.logger = logger

    @property
    def pending_dir(self) -> Path:
        return self.repo_dir / "pending"

    @property
    def claimed_dir(self) -> Path:
        return self.repo_dir / "claimed"

    @property
    def results_dir(self) -> Path:
        return self.repo_dir / "results"

    @property
    def done_dir(self) -> Path:
        return self.repo_dir / "done"

    @property
    def failed_dir(self) -> Path:
        return self.repo_dir / "failed"

    def ensure_layout(self) -> None:
        for name in QUEUE_DIRS:
            path = self.repo_dir / name
            path.mkdir(parents=True, exist_ok=True)
            keep = path / ".gitkeep"
            if not keep.exists():
                keep.touch()

    def repo(self) -> git.Repo:
        return open_repo(self.repo_dir, QueueError)

    def sync(self, max_retries: int | None = 3, retry_delay: int = 5) -> None:
        import time
        repo = self.repo()
        self.logger.info("同步队列仓库：%s", self.repo_dir)

        # 1. 确保本地工作区是干净的，配置 pull.rebase 为 true
        try:
            repo.git.reset("--hard", "HEAD")
            repo.git.clean("-fd")
            repo.git.config("pull.rebase", "true")
        except Exception as exc:
            self.logger.warning("初始化清理队列仓库或配置 pull.rebase 失败：%s", exc)

        attempt = 0
        current_delay = retry_delay
        while True:
            attempt += 1
            try:
                origin = self._origin(repo)
                origin.pull()
                return
            except Exception as exc:
                if max_retries is not None:
                    self.logger.warning(
                        "拉取队列仓库失败（尝试 %s/%s）：%s",
                        attempt, max_retries, exc
                    )
                else:
                    self.logger.warning(
                        "拉取队列仓库失败（尝试 %s）：%s",
                        attempt, exc
                    )
                # 2. 如果拉取失败（如分叉或冲突），则自动回滚并强制重置到远程最新状态
                try:
                    self.logger.info("检测到拉取冲突或错误，正在尝试强制重置本地队列分支到 origin/main...")
                    try:
                        repo.git.rebase("--abort")
                    except Exception:
                        pass
                    origin.fetch()
                    active_branch = repo.active_branch.name
                    repo.git.reset("--hard", f"origin/{active_branch}")
                    repo.git.clean("-fd")
                except Exception as reset_exc:
                    self.logger.warning("自动重置队列仓库失败：%s", reset_exc)

                if max_retries is None or attempt < max_retries:
                    time.sleep(current_delay)
                    if max_retries is None:
                        current_delay = min(current_delay * 2, 60)
                else:
                    raise QueueError(f"Failed to pull queue repo after {max_retries} attempts: {exc}") from exc

    def commit_and_push(self, message: str) -> None:
        repo = self.repo()
        self.logger.info("提交队列更改：%s", message)
        try:
            origin = self._origin(repo)
            commit_all(repo, message, self.logger)
            push_and_check(origin, QueueError)
        except QueueError:
            raise
        except Exception as exc:
            raise QueueError(f"Failed to commit/push queue repo: {exc}") from exc

    def _origin(self, repo: git.Repo):
        if "origin" not in [remote.name for remote in repo.remotes]:
            raise QueueError(
                f"Queue repo has no origin remote: {self.repo_dir}. "
                "Set the shared queue Git remote before running distributed commands."
            )
        return repo.remotes.origin

    def task_exists(self, task_id: str) -> bool:
        for path in self.iter_task_json_files():
            try:
                if Task.from_file(path).task_id == task_id:
                    return True
            except Exception:
                if task_id in path.name:
                    return True
        return False

    def task_is_pending_or_claimed(self, task_id: str) -> Path | None:
        for base in (self.pending_dir, self.claimed_dir):
            if not base.exists():
                continue
            for path in base.rglob("*.json"):
                try:
                    if Task.from_file(path).task_id == task_id:
                        return path
                except Exception:
                    if task_id in path.name:
                        return path
        return None

    def iter_task_json_files(self) -> list[Path]:
        files: list[Path] = []
        for base in (self.pending_dir, self.claimed_dir, self.failed_dir):
            if base.exists():
                files.extend(base.rglob("*.json"))
        for base in (self.results_dir, self.done_dir):
            if base.exists():
                files.extend(base.rglob("task.json"))
        return files

    def add_pending_task(self, task: Task) -> Path:
        self.ensure_layout()
        target = self.pending_dir / task.filename
        self.logger.info("添加待处理任务：%s -> %s", task.task_id, target)
        task.clear_claim()
        task.write_json(target)
        return target

    def find_claimed_task(self, server_id: str) -> tuple[Path, Task] | None:
        server_dir = self.claimed_dir / server_id
        for path in sorted(server_dir.glob("*.json")):
            return path, Task.from_file(path)
        return None

    def iter_results(self) -> list[Path]:
        if not self.results_dir.exists():
            return []
        return sorted(path for path in self.results_dir.iterdir() if path.is_dir())

    def claim_longest_task(self, server_id: str, max_duration_seconds: int) -> tuple[Path, Task] | None:
        self.ensure_layout()
        existing = self.find_claimed_task(server_id)
        if existing:
            self.logger.info("恢复 %s 已认领的现有任务：%s", server_id, existing[1].task_id)
            return existing

        candidates: list[tuple[int, Path, Task]] = []
        for path in self.pending_dir.glob("*.json"):
            task = Task.from_file(path)
            if task.duration <= max_duration_seconds:
                candidates.append((task.duration, path, task))

        if not candidates:
            self.logger.info("未找到待处理任务")
            return None

        _, source, task = max(candidates, key=lambda item: item[0])
        task.mark_claimed(server_id)
        target_dir = self.claimed_dir / server_id
        target = target_dir / source.name
        target_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info("认领任务：%s duration=%ss -> %s", task.task_id, task.duration, target)
        source.unlink()
        task.write_json(target)
        return target, task

    def return_to_pending(self, claimed_path: Path, task: Task, error: str) -> Path:
        task.clear_claim()
        task.last_error = error
        target = self.pending_dir / task.filename
        self.logger.info("将任务返回至待处理：%s reason=%s", task.task_id, error)
        claimed_path.unlink(missing_ok=True)
        task.write_json(target)
        return target

    def move_to_failed(self, claimed_path: Path, task: Task, error: str, server_id: str | None = None) -> Path:
        task.clear_claim()
        task.mark_failed(error, server_id)
        target_dir = self.failed_dir / task.task_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "task.json"
        self.logger.info("将任务移动至失败：%s reason=%s", task.task_id, error)
        claimed_path.unlink(missing_ok=True)
        task.write_json(target)
        return target

    def publish_result(self, claimed_path: Path, task: Task, local_result_dir: Path) -> Path:
        if not local_result_dir.exists():
            raise QueueError(f"Local result directory does not exist: {local_result_dir}")
        target = self.results_dir / task.task_id
        if target.exists():
            self.logger.info("结果已存在，正在替换：%s", target)
            shutil.rmtree(target)
        self.logger.info("发布结果：%s -> %s", local_result_dir, target)
        shutil.copytree(local_result_dir, target)
        claimed_path.unlink(missing_ok=True)
        task.write_json(target / "task.json")
        return target

    def find_task_anywhere(self, task_id: str) -> Path | None:
        for path in self.iter_task_json_files():
            try:
                task = Task.from_file(path)
                if task.task_id == task_id:
                    return path
            except Exception:
                if task_id in path.as_posix():
                    return path
        return None

    def collect_result_to_done(self, result_dir: Path) -> Path:
        task_id = result_dir.name
        target = self.done_dir / task_id
        if target.exists():
            self.logger.info("已完成结果已存在，正在替换：%s", target)
            shutil.rmtree(target)
        self.logger.info("移动结果至已完成：%s -> %s", result_dir, target)
        shutil.move(str(result_dir), str(target))
        return target

    def release_claimed_tasks(self, timeout_seconds: int, target_server_id: str | None = None) -> int:
        released = 0
        for path in self.claimed_dir.rglob("*.json"):
            server_id = path.parent.name
            if target_server_id and server_id != target_server_id:
                continue
            task = Task.from_file(path)
            if not task.claimed_at:
                continue
            if _is_stale(task.claimed_at, timeout_seconds):
                self.return_to_pending(path, task, f"claim timeout after {timeout_seconds}s")
                released += 1
        return released


def _is_stale(claimed_at: str, timeout_seconds: int) -> bool:
    from datetime import datetime

    try:
        claimed = datetime.fromisoformat(claimed_at)
        now = datetime.fromisoformat(now_iso())
    except ValueError:
        return True
    return (now - claimed).total_seconds() > timeout_seconds
