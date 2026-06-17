from __future__ import annotations

import logging
from pathlib import Path

import git


def open_repo(repo_dir: Path, error_cls: type[Exception] = RuntimeError) -> git.Repo:
    try:
        return git.Repo(repo_dir)
    except Exception as exc:
        raise error_cls(f"Not a Git repository: {repo_dir}") from exc


def commit_all(repo: git.Repo, message: str, logger: logging.Logger) -> bool:
    repo.git.add(A=True)
    if not repo.is_dirty(untracked_files=True):
        logger.info("%s 中没有需要提交的更改", repo.working_dir)
        return False
    repo.index.commit(message)
    logger.info("已提交：%s", message)
    return True


def push_and_check(origin, error_cls: type[Exception] = RuntimeError) -> None:
    push_infos = origin.push()
    failures = [
        info.summary
        for info in push_infos
        if info.flags & (git.PushInfo.ERROR | git.PushInfo.REJECTED)
    ]
    if failures:
        raise error_cls(f"Push failed: {'; '.join(failures)}")


def push_and_set_upstream(repo: git.Repo, remote_name: str = "origin", branch_name: str = "main", error_cls: type[Exception] = RuntimeError) -> None:
    try:
        remote = getattr(repo.remotes, remote_name)
    except AttributeError as exc:
        raise error_cls(f"Missing remote: {remote_name}") from exc

    try:
        current_branch = repo.active_branch.name
    except TypeError as exc:
        raise error_cls("Repository is in detached HEAD state") from exc

    push_infos = remote.push(refspec=f"{current_branch}:{branch_name}", set_upstream=True)
    failures = [
        info.summary
        for info in push_infos
        if info.flags & (git.PushInfo.ERROR | git.PushInfo.REJECTED)
    ]
    if failures:
        raise error_cls(f"Push failed: {'; '.join(failures)}")
