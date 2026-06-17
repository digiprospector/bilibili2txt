from __future__ import annotations

import logging
from argparse import Namespace
from pathlib import Path
import git

from bilibili2txt.commands.client import finish
from bilibili2txt.config import CommandContext, load_config
from bilibili2txt.services.gitrepo import GitRepo


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
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return CommandContext(load_config(config_path), "client finish")


def test_finish_commits_and_pushes_data(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    git.Repo.init(data_dir)

    called_commit_and_push = []

    def mock_commit_and_push_all(self, message: str):
        called_commit_and_push.append(message)
        return True

    monkeypatch.setattr(GitRepo, "commit_and_push_all", mock_commit_and_push_all)

    ctx = _context(tmp_path)
    args = Namespace(message="test message")
    code = finish(ctx, args, logging.getLogger("test"))

    assert code == 0
    assert called_commit_and_push == ["test message"]


def test_run_calls_finish_when_wait_is_active(tmp_path: Path, monkeypatch):
    from bilibili2txt.commands import client as client_commands

    called = []
    monkeypatch.setattr(client_commands, "scan", lambda *a: 0)
    monkeypatch.setattr(client_commands, "prepare_audio", lambda *a: 0)
    monkeypatch.setattr(client_commands, "submit", lambda *a: 0)
    monkeypatch.setattr(client_commands, "_wait_for_queue_completion", lambda *a: None)
    monkeypatch.setattr(client_commands, "collect", lambda *a: 0)
    monkeypatch.setattr(client_commands, "render", lambda *a: 0)
    monkeypatch.setattr(client_commands, "sync", lambda *a: 0)
    monkeypatch.setattr(client_commands, "finish", lambda *a: called.append("finish") or 0)

    ctx = _context(tmp_path)
    args = Namespace(wait=True)
    code = client_commands.run(ctx, args, logging.getLogger("test"))

    assert code == 0
    assert "finish" in called

