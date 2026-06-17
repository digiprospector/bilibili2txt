from __future__ import annotations

import logging
from argparse import Namespace
from pathlib import Path

import git
import pytest

from bilibili2txt.commands import init as init_commands
from bilibili2txt.config import CommandContext, load_config


@pytest.fixture(autouse=True)
def _mock_initial_push(monkeypatch):
    monkeypatch.setattr("bilibili2txt.commands.init.push_and_set_upstream", lambda *_args, **_kwargs: None)


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
    return CommandContext(load_config(config_path), "init")


def test_init_queue_creates_git_repo_layout_and_commit(tmp_path: Path, monkeypatch):
    ctx = _context(tmp_path)
    answers = iter(["git@example.com:owner/queue.git", "init queue"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    pushed = {}

    def mock_push_and_set_upstream(repo, remote_name="origin", branch_name="main", error_cls=RuntimeError):
        pushed["repo"] = repo
        pushed["remote_name"] = remote_name
        pushed["branch_name"] = branch_name

    monkeypatch.setattr("bilibili2txt.commands.init.push_and_set_upstream", mock_push_and_set_upstream)

    code = init_commands.queue(ctx, Namespace(), logging.getLogger("test"))

    repo = git.Repo(ctx.config.queue_dir)
    assert code == 0
    assert repo.head.commit.message.strip() == "init queue repo"
    assert repo.remotes.origin.url == "git@example.com:owner/queue.git"
    assert pushed["remote_name"] == "origin"
    assert pushed["branch_name"] == "main"
    for name in ("pending", "claimed", "results", "done", "failed"):
        assert (ctx.config.queue_dir / name / ".gitkeep").exists()


def test_init_data_creates_git_repo_layout_db_config_and_commit(tmp_path: Path, monkeypatch):
    ctx = _context(tmp_path)
    answers = iter(["git@example.com:owner/data.git", "init data"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    pushed = {}

    def mock_push_and_set_upstream(repo, remote_name="origin", branch_name="main", error_cls=RuntimeError):
        pushed["repo"] = repo
        pushed["remote_name"] = remote_name
        pushed["branch_name"] = branch_name

    monkeypatch.setattr("bilibili2txt.commands.init.push_and_set_upstream", mock_push_and_set_upstream)

    code = init_commands.data(ctx, Namespace(), logging.getLogger("test"))

    repo = git.Repo(ctx.config.data_dir)
    assert code == 0
    assert repo.head.commit.message.strip() == "init data repo"
    assert repo.remotes.origin.url == "git@example.com:owner/data.git"
    assert pushed["remote_name"] == "origin"
    assert pushed["branch_name"] == "main"
    assert (ctx.config.data_dir / "config.yaml").exists()
    assert (ctx.config.data_dir / "bilibili2txt.db").exists()
    assert (ctx.config.data_dir / "save" / ".gitkeep").exists()
    assert (ctx.config.data_dir / "tasks" / "submitted" / ".gitkeep").exists()


def test_existing_non_repo_requires_remote_then_confirmation(tmp_path: Path, monkeypatch):
    ctx = _context(tmp_path)
    repo_dir = ctx.config.queue_dir
    repo_dir.mkdir()
    stale = repo_dir / "stale.txt"
    stale.write_text("stale", encoding="utf-8")
    answers = iter(["git@example.com:owner/queue.git", "init queue"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    code = init_commands.queue(ctx, Namespace(), logging.getLogger("test"))

    repo = git.Repo(repo_dir)
    assert code == 0
    assert repo.remotes.origin.url == "git@example.com:owner/queue.git"
    assert not stale.exists()
    assert (repo_dir / "pending" / ".gitkeep").exists()


def test_new_repo_requires_non_empty_remote(tmp_path: Path, monkeypatch):
    ctx = _context(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    with pytest.raises(init_commands.InitError):
        init_commands.queue(ctx, Namespace(), logging.getLogger("test"))


def test_existing_repo_cancel_does_not_delete_content(tmp_path: Path, monkeypatch):
    ctx = _context(tmp_path)
    repo_dir = ctx.config.queue_dir
    repo_dir.mkdir()
    git.Repo.init(repo_dir)
    marker = repo_dir / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")

    with pytest.raises(init_commands.InitError):
        init_commands.queue(ctx, Namespace(), logging.getLogger("test"))

    assert marker.exists()


def test_existing_repo_confirmation_clears_content_and_commits(tmp_path: Path, monkeypatch):
    ctx = _context(tmp_path)
    repo_dir = ctx.config.queue_dir
    repo_dir.mkdir()
    repo = git.Repo.init(repo_dir)
    stale = repo_dir / "stale.txt"
    stale.write_text("stale", encoding="utf-8")
    repo.git.add(A=True)
    repo.index.commit("stale")
    monkeypatch.setattr("builtins.input", lambda _prompt: "init queue")

    code = init_commands.queue(ctx, Namespace(), logging.getLogger("test"))

    repo = git.Repo(repo_dir)
    assert code == 0
    assert not stale.exists()
    assert (repo_dir / "pending" / ".gitkeep").exists()
    assert repo.head.commit.message.strip() == "init queue repo"


def test_empty_repo_skips_confirmation(tmp_path: Path, monkeypatch):
    ctx = _context(tmp_path)
    repo_dir = ctx.config.queue_dir
    repo_dir.mkdir()
    repo = git.Repo.init(repo_dir)

    def mock_input(prompt):
        if prompt.startswith("Enter remote URL"):
            return "git@example.com:owner/queue.git"
        raise AssertionError(f"Unexpected confirmation prompt: {prompt}")

    monkeypatch.setattr("builtins.input", mock_input)

    code = init_commands.queue(ctx, Namespace(), logging.getLogger("test"))
    assert code == 0
    assert repo.remotes.origin.url == "git@example.com:owner/queue.git"
    assert (repo_dir / "pending" / ".gitkeep").exists()
    assert repo.head.commit.message.strip() == "init queue repo"
