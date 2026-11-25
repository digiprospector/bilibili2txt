from __future__ import annotations

import logging
from argparse import Namespace
from pathlib import Path

import pytest

from bilibili2txt.commands import client as client_commands
from bilibili2txt.config import CommandContext, load_config


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
    return CommandContext(load_config(config_path), "client manual")


def _manual_handler():
    handler = getattr(client_commands, "manual", None)
    assert callable(handler), "client manual handler is missing"
    return handler


def test_manual_adds_one_video_then_starts_at_wait(tmp_path, monkeypatch):
    events: list[tuple] = []

    def add(_ctx, args, _logger):
        events.append(("add", args.bvid, args.category))
        return 0

    def run_pipeline(_ctx, args, _logger, from_step=None):
        events.append(("pipeline", from_step, args.command, args.server))
        return 0

    monkeypatch.setattr(client_commands, "add", add)
    monkeypatch.setattr(client_commands, "run_pipeline", run_pipeline)
    monkeypatch.setattr(
        client_commands, "scan", lambda *_args: pytest.fail("manual must not scan")
    )
    args = Namespace(
        bvid="BVxxxx",
        category="历史",
        server="browser",
        account=None,
        command="manual",
    )

    code = _manual_handler()(
        _context(tmp_path), args, logging.getLogger("test")
    )

    assert code == 0
    assert events == [
        ("add", "BVxxxx", "历史"),
        ("pipeline", "wait", "manual", "browser"),
    ]


def test_manual_stops_when_add_fails(tmp_path, monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(
        client_commands, "add", lambda *_args: events.append("add") or 1
    )
    monkeypatch.setattr(
        client_commands,
        "run_pipeline",
        lambda *_args, **_kwargs: pytest.fail("pipeline must not run after add fails"),
    )
    args = Namespace(
        bvid="BVxxxx",
        category="投资",
        server="browser",
        account=None,
        command="manual",
    )

    code = _manual_handler()(
        _context(tmp_path), args, logging.getLogger("test")
    )

    assert code == 1
    assert events == ["add"]


def test_manual_cli_requires_account_before_adding(tmp_path, monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(
        client_commands,
        "add",
        lambda *_args: events.append("add") or pytest.fail("add must not run"),
    )
    args = Namespace(
        bvid="BVxxxx",
        category="投资",
        server="cli",
        account=None,
        command="manual",
    )

    code = _manual_handler()(
        _context(tmp_path), args, logging.getLogger("test")
    )

    assert code != 0
    assert events == []


def test_manual_cli_passes_account_to_remaining_pipeline(tmp_path, monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(client_commands, "add", lambda *_args: 0)
    monkeypatch.setattr(
        client_commands,
        "run_pipeline",
        lambda _ctx, args, _logger, from_step=None: calls.append(
            (from_step, args.server, args.account, args.command)
        )
        or 0,
    )
    args = Namespace(
        bvid="BVxxxx",
        category="投资",
        server="cli",
        account="account-a",
        command="manual",
    )

    code = _manual_handler()(
        _context(tmp_path), args, logging.getLogger("test")
    )

    assert code == 0
    assert calls == [("wait", "cli", "account-a", "manual")]
