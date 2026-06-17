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

    assert set(role_actions[0].choices) == {"client", "server", "admin", "init"}


def test_init_commands_match_public_contract():
    parser = build_parser()

    assert _choices(parser, "init") == {"data", "queue"}


def test_client_commands_match_public_contract():
    parser = build_parser()

    assert _choices(parser, "client") == {
        "scan",
        "submit",
        "prepare-audio",
        "collect",
        "render",
        "sync",
        "run",
        "resubmit-missing",
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
