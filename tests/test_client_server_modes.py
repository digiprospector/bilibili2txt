from __future__ import annotations

import logging
import sys
from argparse import Namespace
from types import ModuleType

from bilibili2txt.commands import client as client_commands
from bilibili2txt.commands import colab as colab_commands
from bilibili2txt.config import CommandContext, load_config


def _context(tmp_path, command: str) -> CommandContext:
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
    return CommandContext(load_config(config_path), f"client {command}")


def _patch_pipeline(monkeypatch):
    events: list[str] = []
    chrome = ModuleType("chrome_bookmark_manager")
    chrome.manage_chrome = lambda action, _logger: events.append(f"chrome-{action}")
    monkeypatch.setitem(sys.modules, "chrome_bookmark_manager", chrome)
    monkeypatch.setattr(
        client_commands,
        "_wait_for_queue_completion",
        lambda *_args: events.append("wait"),
    )
    monkeypatch.setattr(
        client_commands, "collect", lambda *_args: events.append("collect") or 0
    )
    monkeypatch.setattr(
        client_commands, "render", lambda *_args: events.append("render") or 0
    )
    monkeypatch.setattr(
        client_commands, "sync", lambda *_args: events.append("sync") or 0
    )
    monkeypatch.setattr(
        client_commands, "finish", lambda *_args: events.append("finish") or 0
    )
    monkeypatch.setattr(
        client_commands,
        "_send_dingtalk_run_notification",
        lambda *_args, **_kwargs: None,
    )
    return events


def test_browser_server_keeps_chrome_and_queue_wait(tmp_path, monkeypatch):
    events = _patch_pipeline(monkeypatch)
    args = Namespace(server="browser", command="run", wait=True)

    code = client_commands.run_pipeline(
        _context(tmp_path, "run"), args, logging.getLogger("test"), from_step="wait"
    )

    assert code == 0
    assert events == [
        "chrome-open",
        "wait",
        "chrome-close",
        "collect",
        "render",
        "sync",
        "finish",
    ]


def test_cli_run_uses_colab_run_all_without_browser(tmp_path, monkeypatch):
    events = _patch_pipeline(monkeypatch)
    monkeypatch.setattr(
        client_commands,
        "colab_run_all",
        lambda *_args: events.append("run-all") or 0,
        raising=False,
    )
    args = Namespace(server="cli", command="run", wait=True)

    code = client_commands.run_pipeline(
        _context(tmp_path, "run"), args, logging.getLogger("test"), from_step="wait"
    )

    assert code == 0
    assert events == ["run-all", "collect", "render", "sync", "finish"]


def test_cli_process_uses_the_selected_account(tmp_path, monkeypatch):
    events = _patch_pipeline(monkeypatch)
    monkeypatch.setattr(
        client_commands,
        "colab_run",
        lambda _ctx, args, _logger: events.append(f"run:{args.account}") or 0,
        raising=False,
    )
    args = Namespace(
        server="cli", command="process", account="account-a", wait=True
    )

    code = client_commands.run_pipeline(
        _context(tmp_path, "process"),
        args,
        logging.getLogger("test"),
        from_step="wait",
    )

    assert code == 0
    assert events == ["run:account-a", "collect", "render", "sync", "finish"]


def test_cli_failure_stops_before_collect(tmp_path, monkeypatch):
    events = _patch_pipeline(monkeypatch)
    monkeypatch.setattr(
        client_commands,
        "colab_run_all",
        lambda *_args: events.append("run-all") or 7,
        raising=False,
    )
    args = Namespace(server="cli", command="run", wait=True)

    code = client_commands.run_pipeline(
        _context(tmp_path, "run"), args, logging.getLogger("test"), from_step="wait"
    )

    assert code == 7
    assert events == ["run-all"]


def test_colab_status_lists_configured_account_names(tmp_path, monkeypatch, caplog):
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
                "colab:",
                "  accounts:",
                "    - name: account-a",
                "    - name: account-b",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ctx = CommandContext(load_config(config_path), "colab status")
    monkeypatch.setattr(colab_commands, "_run_wsl", lambda *_args, **_kwargs: 0)
    logger = logging.getLogger("test-colab-status")

    with caplog.at_level(logging.INFO):
        code = colab_commands.status(ctx, Namespace(account=None), logger)

    assert code == 0
    assert "=== account-a ===" in caplog.text
    assert "=== account-b ===" in caplog.text
