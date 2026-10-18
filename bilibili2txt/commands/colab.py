from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import yaml

from ..config import CommandContext


def _colab_key_path(account: str) -> str:
    return os.path.expanduser(f"~/.config/colab-cli/account-{account}.json")


def _wsl_project_dir() -> str:
    """Convert the Windows project root to its WSL path (/mnt/c/...)."""
    root = Path(__file__).resolve().parent.parent.parent
    drive = root.drive.replace(":", "").lower()
    path_str = str(root).replace("\\", "/").split(":", 1)[-1]
    return f"/mnt/{drive}{path_str}"


def _load_account_names(config) -> list[str]:
    """Read profile names from the chrome bookmark config YAML."""
    bookmark_path = config.get("colab.bookmark_config")
    if not bookmark_path:
        return []
    bookmark_file = Path(bookmark_path)
    if not bookmark_file.is_absolute():
        bookmark_file = Path(__file__).resolve().parent.parent.parent / bookmark_file
    if not bookmark_file.exists():
        return []
    with open(bookmark_file, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [p["name"] for p in data.get("profiles", []) if p.get("name")]


def _build_wsl_command(config, args: list[str]) -> list[str]:
    proxy = config.get("client.proxy") or ""
    gpu = config.get("colab.gpu") or "T4"
    notebook = config.get("colab.notebook") or "notebooks/bilibili2txt_server_colab.ipynb"

    exports = ""
    if proxy:
        exports = f"export https_proxy={proxy} http_proxy={proxy}; "

    env_prefix = ""
    if args and args[0] == "colab":
        session_name = None
        for i, a in enumerate(args):
            if a == "-s" and i + 1 < len(args):
                session_name = args[i + 1]
                break
        if session_name:
            env_prefix = f"GOOGLE_APPLICATION_CREDENTIALS={_colab_key_path(session_name)} "
    return ["wsl.exe", "-e", "bash", "-c", env_prefix + exports + " ".join(args)]


def _run_wsl(cmd: list[str], logger: logging.Logger) -> int:
    logger.info("运行: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        logger.info(result.stdout.rstrip())
    if result.stderr:
        logger.warning(result.stderr.rstrip())
    return result.returncode


def run(ctx: CommandContext, args, logger: logging.Logger) -> int:
    account = args.account
    key_path = _colab_key_path(account)
    gpu = ctx.config.get("colab.gpu") or "T4"
    notebook = ctx.config.get("colab.notebook") or "notebooks/bilibili2txt_server_colab.ipynb"

    base = ["colab"]
    session_name = account

    # 创建 GPU session
    ret = _run_wsl(
        _build_wsl_command(
            ctx.config,
            base + ["new", "-s", session_name, "--gpu", gpu],
        ),
        logger,
    )
    if ret != 0:
        logger.error("创建 session %s 失败", session_name)
        return ret

    # 执行 notebook
    project_dir_wsl = _wsl_project_dir()
    ret = _run_wsl(
        _build_wsl_command(
            ctx.config,
            base + ["exec", "-s", session_name, "-f", f"{project_dir_wsl}/{notebook}"],
        ),
        logger,
    )

    # 无论成功失败都尝试关停 VM
    _run_wsl(
        _build_wsl_command(
            ctx.config,
            base + ["stop", "-s", session_name],
        ),
        logger,
    )

    if ret != 0:
        logger.error("执行 notebook 失败")
    else:
        logger.info("执行完成，session %s 已关停", session_name)
    return ret


def run_all(ctx: CommandContext, args, logger: logging.Logger) -> int:
    accounts = ctx.config.get("colab.accounts") or _load_account_names(ctx.config)
    if not accounts:
        logger.error("配置中缺少 colab.accounts 列表")
        return 1

    exit_code = 0
    for account in accounts:
        logger.info("=== 运行账号: %s ===", account)
        args.account = account
        ret = run(ctx, args, logger)
        if ret != 0:
            exit_code = ret
    return exit_code


def status(ctx: CommandContext, args, logger: logging.Logger) -> int:
    accounts = ctx.config.get("colab.accounts") or _load_account_names(ctx.config)
    if args.account:
        accounts = [args.account]
    if not accounts:
        logger.error("无法获取账号列表，也未指定 --account")
        return 1

    exit_code = 0
    for account in accounts:
        base = ["colab"]
        logger.info("=== %s ===", account)
        ret = _run_wsl(
            _build_wsl_command(ctx.config, base + ["status", "-s", account]),
            logger,
        )
        if ret != 0:
            exit_code = ret
    return exit_code


def stop(ctx: CommandContext, args, logger: logging.Logger) -> int:
    account = args.account
    base = ["colab", "--config", _colab_config_path(account)]
    return _run_wsl(
        _build_wsl_command(ctx.config, base + ["stop", "-s", account]),
        logger,
    )


def login(ctx: CommandContext, args, logger: logging.Logger) -> int:
    """Trigger OAuth flow for a given account and save its credentials."""
    account = args.account
    key_path = _colab_key_path(account)
    base = ["colab"]
    logger.info("开始登录账号: %s (key: %s)", account, key_path)

    ret = _run_wsl(
        _build_wsl_command(ctx.config, base + ["whoami"]),
        logger,
    )
    if ret == 0:
        logger.info("账号 %s 已登录，凭据有效", account)
        return 0

    logger.info("凭据不存在或已过期，需要重新认证")
    ret = _run_wsl(
        _build_wsl_command(ctx.config, base + ["new", "-s", "login-check"]),
        logger,
    )
    if ret != 0:
        logger.error("登录失败: %s", account)
        return ret

    _run_wsl(
        _build_wsl_command(ctx.config, base + ["stop", "-s", "login-check"]),
        logger,
    )
    logger.info("登录成功: %s", account)
    return 0


def check(ctx: CommandContext, args, logger: logging.Logger) -> int:
    """Test whether each account's session is alive and usable."""
    accounts = ctx.config.get("colab.accounts") or _load_account_names(ctx.config)
    if args.account:
        accounts = [args.account]
    if not accounts:
        logger.error("无法获取账号列表，也未指定 --account")
        return 1

    exit_code = 0
    for account in accounts:
        base = ["colab"]
        logger.info("=== 检查账号: %s ===", account)

        ret = _run_wsl(
            _build_wsl_command(ctx.config, base + ["status", "-s", account]),
            logger,
        )
        if ret != 0:
            logger.warning("账号 %s session 不可用 (status 返回 %s)", account, ret)
            exit_code = ret
            continue

        # 尝试执行简单代码验证 kernel 可用
        ret = _run_wsl(
            _build_wsl_command(
                ctx.config,
                base + ["exec", "-s", account],
            ),
            logger,
        )
        if ret != 0:
            logger.warning("账号 %s kernel 不可用 (exec 返回 %s)", account, ret)
            exit_code = ret
        else:
            logger.info("账号 %s 正常", account)
    return exit_code
