from __future__ import annotations

import logging
import shutil
from pathlib import Path

import git

from ..config import CommandContext, DB_FILENAME
from ..database import ClientDatabase
from ..paths import ROOT_DIR
from ..services.git_helpers import open_repo, commit_all, push_and_set_upstream
from ..services.gitqueue import GitQueue


class InitError(RuntimeError):
    pass


def data(ctx: CommandContext, _args, logger: logging.Logger) -> int:
    repo_dir = ctx.config.data_dir
    _prepare_repo(repo_dir, "data", logger)
    _init_data_layout(ctx, logger)
    _commit_repo(repo_dir, "init data repo", logger)
    _push_initial_main(repo_dir, "data", logger)
    logger.info("Data repo initialized: %s", repo_dir)
    return 0


def queue(ctx: CommandContext, _args, logger: logging.Logger) -> int:
    repo_dir = ctx.config.queue_dir
    _prepare_repo(repo_dir, "queue", logger)
    GitQueue(repo_dir, logger).ensure_layout()
    _commit_repo(repo_dir, "init queue repo", logger)
    _push_initial_main(repo_dir, "queue", logger)
    logger.info("Queue repo initialized: %s", repo_dir)
    return 0


def _prepare_repo(repo_dir: Path, name: str, logger: logging.Logger) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    if not _is_git_repo(repo_dir):
        remote_url = _prompt_remote_url(name, repo_dir)
        logger.info("%s directory is not a Git repo; running git init: %s", name.capitalize(), repo_dir)
        repo = git.Repo.init(repo_dir)
        repo.create_remote("origin", remote_url)
        logger.info("Added origin remote for %s repo: %s", name, remote_url)

    repo = git.Repo(repo_dir)
    has_files = any(child.name != ".git" for child in repo_dir.iterdir())
    if has_files:
        _print_repo_summary(repo, repo_dir, name, logger)
        if not _confirm_reinitialize(name, repo_dir):
            raise InitError(f"Cancelled {name} initialization")
        _clear_repo_worktree(repo_dir, logger)
    if "origin" not in [remote.name for remote in repo.remotes]:
        remote_url = _prompt_remote_url(name, repo_dir)
        repo.create_remote("origin", remote_url)
        logger.info("Added origin remote for %s repo: %s", name, remote_url)


def _init_data_layout(ctx: CommandContext, logger: logging.Logger) -> None:
    data_dir = ctx.config.data_dir
    for relative in (
        "userdata",
        "save",
        "markdown",
        "tasks/submitted",
    ):
        path = data_dir / relative
        path.mkdir(parents=True, exist_ok=True)
        keep = path / ".gitkeep"
        if not keep.exists():
            keep.touch()
        logger.info("Ensure data directory: %s", path)

    config_target = data_dir / "config.yaml"
    config_source = ROOT_DIR / "config.example.yaml"
    if config_source.exists():
        shutil.copy2(config_source, config_target)
        logger.info("Created data config: %s", config_target)
    else:
        logger.warning("Missing config.example.yaml; skip data config copy")

    ClientDatabase(data_dir / DB_FILENAME).initialize()
    logger.info("Initialized client database: %s", data_dir / DB_FILENAME)


def _is_git_repo(repo_dir: Path) -> bool:
    try:
        git.Repo(repo_dir)
        return True
    except git.InvalidGitRepositoryError:
        return False
    except git.NoSuchPathError:
        return False


def _print_repo_summary(repo: git.Repo, repo_dir: Path, name: str, logger: logging.Logger) -> None:
    logger.warning("%s directory is already a Git repo: %s", name.capitalize(), repo_dir)
    logger.warning("Current branch: %s", _branch_name(repo))
    remotes = _remote_lines(repo)
    if remotes:
        for line in remotes:
            logger.warning("Remote: %s", line)
    else:
        logger.warning("Remote: <none>")
    status = repo.git.status("--short")
    logger.warning("Status:\n%s", status if status else "<clean>")
    logger.warning("Initializing will delete all files in %s except .git/", repo_dir)


def _branch_name(repo: git.Repo) -> str:
    try:
        return repo.active_branch.name
    except TypeError:
        return "<detached>"


def _remote_lines(repo: git.Repo) -> list[str]:
    lines: list[str] = []
    for remote in repo.remotes:
        for url in remote.urls:
            lines.append(f"{remote.name}\t{url}")
    return lines


def _prompt_remote_url(name: str, repo_dir: Path) -> str:
    remote_url = input(f"Enter remote URL for {name} repo at {repo_dir}: ").strip()
    if not remote_url:
        raise InitError(f"Remote URL is required for {name} initialization")
    return remote_url


def _confirm_reinitialize(name: str, repo_dir: Path) -> bool:
    expected = f"init {name}"
    answer = input(
        f"Type '{expected}' to clear and reinitialize {repo_dir}: "
    ).strip()
    return answer == expected


def _clear_repo_worktree(repo_dir: Path, logger: logging.Logger) -> None:
    for child in repo_dir.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        logger.info("Deleted existing repo content: %s", child)


def _commit_repo(repo_dir: Path, message: str, logger: logging.Logger) -> None:
    repo = open_repo(repo_dir)
    commit_all(repo, message, logger)


def _push_initial_main(repo_dir: Path, name: str, logger: logging.Logger) -> None:
    repo = open_repo(repo_dir, InitError)
    logger.info("Push %s repo and set upstream: %s -> origin/main", name, repo_dir)
    push_and_set_upstream(repo, branch_name="main", error_cls=InitError)
