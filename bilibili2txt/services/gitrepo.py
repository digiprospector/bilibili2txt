from __future__ import annotations

import logging
from pathlib import Path

import git

from .git_helpers import open_repo, commit_all, push_and_check


class GitRepoError(RuntimeError):
    pass


class GitRepo:
    def __init__(self, repo_dir: Path, logger: logging.Logger):
        self.repo_dir = repo_dir
        self.logger = logger

    def repo(self) -> git.Repo:
        return open_repo(self.repo_dir, GitRepoError)

    def commit_and_push_all(self, message: str) -> bool:
        repo = self.repo()
        self.logger.info("检查 Git 仓库更改：%s", self.repo_dir)
        if not commit_all(repo, message, self.logger):
            return False
        self.logger.info("已提交数据仓库：%s", message)
        push_and_check(repo.remotes.origin, GitRepoError)
        self.logger.info("推送仓库成功：%s", self.repo_dir)
        return True


