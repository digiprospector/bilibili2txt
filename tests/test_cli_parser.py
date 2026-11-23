from __future__ import annotations

import pytest

from bilibili2txt.cli import build_parser


def _choices(parser, role: str) -> set[str]:
    role_actions = [action for action in parser._actions if getattr(action, "choices", None)]
    role_parser = role_actions[0].choices[role]
    command_actions = [action for action in role_parser._actions if getattr(action, "choices", None)]
    return set(command_actions[0].choices)


def test_top_level_commands_include_init():
    parser = build_parser()
    role_actions = [action for action in parser._actions if getattr(action, "choices", None)]

    assert set(role_actions[0].choices) == {"client", "server", "admin", "init", "site", "colab"}


def test_init_commands_match_public_contract():
    parser = build_parser()

    assert _choices(parser, "init") == {"data", "queue", "site"}


def test_client_commands_match_public_contract():
    parser = build_parser()

    assert _choices(parser, "client") == {
        "scan",
        "submit",
        "prepare-audio",
        "add",
        "categories",
        "collect",
        "render",
        "sync",
        "run",
        "resume",
        "process",
        "resubmit-missing",
        "clean-favorites",
        "finish",
    }


def test_admin_removed_commands_are_absent():
    parser = build_parser()
    admin_commands = _choices(parser, "admin")

    assert "migrate-main-db" in admin_commands
    assert "chat" not in admin_commands
    assert "retry-failed" not in admin_commands
    assert "requeue-missing" not in admin_commands
    assert "recollect-missing" not in admin_commands


def test_client_no_recollect_missing_alias():
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["client", "recollect-missing"])


def test_client_run_server_defaults_to_browser():
    args = build_parser().parse_args(["client", "run"])

    assert args.server == "browser"


def test_client_run_accepts_cli_server():
    args = build_parser().parse_args(["client", "run", "--server", "cli"])

    assert args.server == "cli"


def test_client_run_rejects_unknown_server():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["client", "run", "--server", "unknown"])


def test_client_process_accepts_bvid_and_defaults():
    args = build_parser().parse_args(["client", "process", "BVxxxx"])

    assert args.bvid == "BVxxxx"
    assert args.category == "投资"
    assert args.server == "browser"
    assert args.account is None


def test_client_process_accepts_server_account_and_category():
    args = build_parser().parse_args(
        ["client", "process", "BVxxxx", "--server", "cli", "--account", "account-a", "--category", "历史"]
    )

    assert args.server == "cli"
    assert args.account == "account-a"
    assert args.category == "历史"

