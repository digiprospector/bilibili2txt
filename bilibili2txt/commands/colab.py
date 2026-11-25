from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..config import AppConfig, CommandContext, is_manual_mode


DEFAULT_GPU = "T4"
DEFAULT_NOTEBOOK = "notebooks/bilibili2txt_server_colab.ipynb"
DEFAULT_MANUAL_NOTEBOOK = "notebooks/bilibili2txt_server_colab_manual.ipynb"
DEFAULT_COMMAND_TIMEOUT = 30
DEFAULT_MOUNT_TIMEOUT = 150
# 每个 WSL 用户下只维护一个业务 session，账号由 WSL 用户区分。
SESSION_NAME = "b2t"
# colab-cli 按 WSL 用户保存 OAuth 凭据。
TOKEN_FILE = "$HOME/.config/colab-cli/token.json"
# colab exec 的 --timeout 默认只有 30 秒，notebook 需要长期运行，这里给一个大值。
NOTEBOOK_EXEC_TIMEOUT = 10**9

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class ColabAccount:
    """A WSL user; each user owns an isolated ``$HOME`` and colab-cli state."""

    name: str


def _to_wsl_path(path: Path) -> str:
    """Convert a Windows path to its WSL mount path (/mnt/c/...)."""
    resolved = path.resolve()
    if os.name != "nt":
        return str(resolved)
    drive = resolved.drive.rstrip(":").lower()
    tail = str(resolved)[len(resolved.drive):].replace("\\", "/")
    return f"/mnt/{drive}{tail}" if drive else tail


def _load_account_names(config: AppConfig) -> list[str]:
    """Read profile names from the chrome bookmark config YAML."""
    bookmark_path = config.get("colab.bookmark_config")
    if not bookmark_path:
        return []
    bookmark_file = Path(bookmark_path).expanduser()
    if not bookmark_file.is_absolute():
        bookmark_file = PROJECT_DIR / bookmark_file
    if not bookmark_file.exists():
        return []
    with open(bookmark_file, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [str(p["name"]) for p in data.get("profiles", []) if p.get("name")]


def _resolve_accounts(config: AppConfig) -> list[ColabAccount]:
    """Return configured accounts, falling back to bookmark profile names."""
    raw = config.get("colab.accounts")
    accounts: list[ColabAccount] = []
    if raw:
        for item in raw:
            if isinstance(item, str):
                name = item.strip()
                if name:
                    accounts.append(ColabAccount(name=name))
            elif isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                accounts.append(ColabAccount(name=name))

    if not accounts:
        accounts = [ColabAccount(name=name) for name in _load_account_names(config)]

    deduplicated: list[ColabAccount] = []
    seen: set[str] = set()
    for account in accounts:
        if account.name in seen:
            continue
        seen.add(account.name)
        deduplicated.append(account)
    return deduplicated


def _find_account(config: AppConfig, name: str | None) -> ColabAccount | None:
    if not name:
        return None
    for account in _resolve_accounts(config):
        if account.name == name:
            return account
    return ColabAccount(name=name)


def _build_wsl_command(
    config: AppConfig,
    argv: list[str],
    *,
    account: ColabAccount,
) -> list[str]:
    """Build a ``wsl.exe`` invocation that runs as the given WSL user."""
    parts = [f"cd {shlex.quote(_to_wsl_path(PROJECT_DIR))}"]

    proxy = _proxy(config)
    if proxy:
        quoted_proxy = shlex.quote(str(proxy))
        parts.append(f"export https_proxy={quoted_proxy} http_proxy={quoted_proxy}")

    command = " ".join(shlex.quote(str(arg)) for arg in argv)
    parts.append(command)
    return [
        "wsl.exe",
        "-u",
        account.name,
        "-e",
        "bash",
        "-lc",
        " && ".join(parts),
    ]


def _proxy(config: AppConfig) -> str:
    """Proxy used by colab-cli."""
    return str(config.get("client.proxy") or "")


def _command_timeout(config: AppConfig) -> int:
    value = config.get("colab.command_timeout_seconds")
    return int(value) if value is not None else DEFAULT_COMMAND_TIMEOUT


def _mount_timeout(config: AppConfig) -> int:
    value = config.get("colab.mount_timeout_seconds")
    if value is not None:
        return int(value)
    return max(_command_timeout(config), DEFAULT_MOUNT_TIMEOUT)


def _run_wsl(
    cmd: list[str],
    logger: logging.Logger,
    *,
    capture: bool = True,
    timeout: int | None = None,
    output: list[str] | None = None,
) -> int:
    logger.info("运行: %s", subprocess.list2cmdline(cmd))
    try:
        if capture:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            if output is not None:
                output.append(result.stdout or "")
            if result.stdout:
                logger.info(result.stdout.rstrip())
            if result.stderr:
                logger.warning(result.stderr.rstrip())
            return result.returncode
        return subprocess.run(cmd, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        logger.error("命令超时（%s 秒），请检查 WSL 网络或代理设置", timeout)
        return 124
    except FileNotFoundError:
        logger.error("找不到 wsl.exe，请确认已安装并启用 WSL")
        return 127


def _gpu(config: AppConfig) -> str:
    return str(config.get("colab.gpu") or DEFAULT_GPU)


def _notebook_wsl_path(config: AppConfig, *, manual: bool = False) -> str:
    default_nb = DEFAULT_MANUAL_NOTEBOOK if manual else DEFAULT_NOTEBOOK
    key = "colab.manual_notebook" if manual else "colab.notebook"
    notebook = Path(config.get(key) or default_nb).expanduser()
    if not notebook.is_absolute():
        notebook = PROJECT_DIR / notebook
    return _to_wsl_path(notebook)


def _require_account(
    config: AppConfig, args, logger: logging.Logger
) -> ColabAccount | None:
    account = _find_account(config, getattr(args, "account", None))
    if account is None:
        logger.error("请通过 --account 指定 colab 账号")
    return account


def run(ctx: CommandContext, args, logger: logging.Logger) -> int:
    account = _require_account(ctx.config, args, logger)
    if account is None:
        return 2

    session = SESSION_NAME
    manual_mode = is_manual_mode(ctx, args)
    notebook_wsl_path = _notebook_wsl_path(ctx.config, manual=manual_mode)
    logger.info("启动账号 %s (manual=%s, notebook=%s)", account.name, manual_mode, notebook_wsl_path)

    # colab new 遇到同名 session 会直接覆盖本地记录，旧 VM 会变成孤儿，
    # 所以先停掉可能残留的 session（stop 对不存在的 session 是幂等的）。
    _run_wsl(
        _build_wsl_command(
            ctx.config,
            ["colab", "stop", "-s", session],
            account=account,
        ),
        logger,
        timeout=_command_timeout(ctx.config),
    )

    ret = _run_wsl(
        _build_wsl_command(
            ctx.config,
            ["colab", "new", "-s", session, "--gpu", _gpu(ctx.config)],
            account=account,
        ),
        logger,
        timeout=_command_timeout(ctx.config),
    )
    if ret != 0:
        logger.error("创建 session %s 失败", session)
        return ret

    try:
        mount_ret = _run_wsl(
            _build_wsl_command(
                ctx.config,
                ["colab", "dfs", "mount", "-s", session],
                account=account,
            ),
            logger,
            timeout=_mount_timeout(ctx.config),
        )
        if mount_ret != 0:
            logger.error("挂载 Google Drive 失败 (session=%s)", session)
            return mount_ret

        ls_output: list[str] = []
        ls_ret = _run_wsl(
            _build_wsl_command(
                ctx.config,
                ["colab", "ls", "/content/drive", "-s", session],
                account=account,
            ),
            logger,
            timeout=_command_timeout(ctx.config),
            output=ls_output,
        )
        if ls_ret != 0:
            logger.error("检查 Google Drive 挂载目录失败 (session=%s)", session)
            return ls_ret
        if ls_output and "MyDrive" not in "".join(ls_output):
            logger.error("Google Drive 未成功挂载，/content/drive 中未检测到 MyDrive (session=%s)", session)
            return 1

        logger.info("Google Drive 挂载验证成功，开始执行 notebook...")
        ret = _run_wsl(
            _build_wsl_command(
                ctx.config,
                [
                    "colab",
                    "exec",
                    "-s",
                    session,
                    "-f",
                    notebook_wsl_path,
                    "--timeout",
                    str(NOTEBOOK_EXEC_TIMEOUT),
                ],
                account=account,
            ),
            logger,
        )
    finally:
        _run_wsl(
            _build_wsl_command(
                ctx.config,
                ["colab", "stop", "-s", session],
                account=account,
            ),
            logger,
            timeout=_command_timeout(ctx.config),
        )

    if ret != 0:
        logger.error("账号 %s 执行 notebook 失败", account.name)
    else:
        logger.info("账号 %s 执行完成，session 已关停", account.name)
    return ret


def run_all(ctx: CommandContext, args, logger: logging.Logger) -> int:
    accounts = _resolve_accounts(ctx.config)
    if not accounts:
        logger.error("配置中缺少 colab.accounts 列表，且无法从 bookmark 配置读取账号")
        return 1

    base = [sys.executable, str(PROJECT_DIR / "b2t.py")]
    if ctx.config.config_path:
        base += ["--config", str(ctx.config.config_path)]

    processes: list[tuple[str, subprocess.Popen]] = []
    for account in accounts:
        cmd = base + ["colab", "run", "--account", account.name]
        logger.info("启动账号 %s: %s", account.name, " ".join(cmd))
        processes.append((account.name, subprocess.Popen(cmd, cwd=str(PROJECT_DIR))))

    exit_code = 0
    try:
        for name, process in processes:
            code = process.wait()
            if code != 0:
                logger.error("账号 %s 退出码 %s", name, code)
                exit_code = exit_code or code
    except KeyboardInterrupt:
        logger.warning("收到中断，正在停止所有账号的 session...")
        for account in accounts:
            _run_wsl(
                _build_wsl_command(
                    ctx.config,
                    ["colab", "stop", "-s", SESSION_NAME],
                    account=account,
                ),
                logger,
                timeout=_command_timeout(ctx.config),
            )
        for _, process in processes:
            if process.poll() is None:
                process.terminate()
        raise
    return exit_code


def _select_accounts(
    config: AppConfig, args, logger: logging.Logger
) -> list[ColabAccount] | None:
    name = getattr(args, "account", None)
    if name:
        return [ColabAccount(name=name)]
    accounts = _resolve_accounts(config)
    if not accounts:
        logger.error("无法获取账号列表，也未指定 --account")
        return None
    return accounts


def status(ctx: CommandContext, args, logger: logging.Logger) -> int:
    accounts = _select_accounts(ctx.config, args, logger)
    if accounts is None:
        return 1

    exit_code = 0
    for account in accounts:
        logger.info("=== %s ===", account.name)
        ret = _run_wsl(
            _build_wsl_command(
                ctx.config,
                ["colab", "status", "-s", SESSION_NAME],
                account=account,
            ),
            logger,
            timeout=_command_timeout(ctx.config),
        )
        if ret != 0:
            exit_code = exit_code or ret
    return exit_code


def stop(ctx: CommandContext, args, logger: logging.Logger) -> int:
    account = _require_account(ctx.config, args, logger)
    if account is None:
        return 2
    return _run_wsl(
        _build_wsl_command(
            ctx.config,
            ["colab", "stop", "-s", SESSION_NAME],
            account=account,
        ),
        logger,
        timeout=_command_timeout(ctx.config),
    )


def login(ctx: CommandContext, args, logger: logging.Logger) -> int:
    """Log in a WSL user interactively, printing the Google authorization URL."""
    account = _require_account(ctx.config, args, logger)
    if account is None:
        return 2

    logger.info("账号: %s（WSL 用户）", account.name)

    has_token = _run_wsl(
        _build_wsl_command(
            ctx.config,
            ["bash", "-c", f'test -f "{TOKEN_FILE}"'],
            account=account,
        ),
        logger,
        timeout=_command_timeout(ctx.config),
    )
    if has_token == 0:
        ret = _run_wsl(
            _build_wsl_command(ctx.config, ["colab", "whoami"], account=account),
            logger,
            timeout=_command_timeout(ctx.config),
        )
        if ret == 0:
            logger.info("账号 %s 已登录", account.name)
            return 0
        logger.warning("账号 %s 的凭据已失效，需要重新登录", account.name)
    else:
        logger.info("账号 %s 尚未登录", account.name)

    logger.info("请在浏览器打开下方 Google 授权地址，授权后把授权码粘贴回终端")
    ret = _run_wsl(
        _build_wsl_command(ctx.config, ["colab", "whoami"], account=account),
        logger,
        capture=False,
        timeout=None,
    )
    if ret != 0:
        logger.error("账号 %s 登录失败", account.name)
        return ret

    logger.info("账号 %s 登录成功", account.name)
    return 0
