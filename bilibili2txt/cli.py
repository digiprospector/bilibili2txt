from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .config import CommandContext, ConfigError, load_config
from .commands.init import data as init_data, queue as init_queue, InitError
from .commands.client import collect as client_collect, finish as client_finish, prepare_audio as client_prepare_audio, render as client_render, resubmit_missing as client_resubmit_missing, run as client_run, scan as client_scan, submit as client_submit, sync as client_sync
from .commands.admin import (
    check_ai as admin_check_ai,
    check_missing as admin_check_missing,
    download_audio as admin_download_audio,
    download_audio_upload as admin_download_audio_upload,
    fix_summaries as admin_fix_summaries,
    migrate_main_db as admin_migrate_main_db,
    push_data as admin_push_data,
    resummarize as admin_resummarize,
    webdav_clean as admin_webdav_clean,
    webdav_upload as admin_webdav_upload,
)
from .commands.server import claim as server_claim, release_claimed as server_release_claimed, run as server_run, transcribe as server_transcribe, publish as server_publish, once as server_once
from .logging import log_command_finish, log_command_start, setup_logger


# ---------------------------------------------------------------------------
# Reusable argument specs: (name_or_flags, kwargs_for_add_argument)
# ---------------------------------------------------------------------------
ARG_INPUT = (("-i", "--input"), {})
ARG_FORCE = (("-f", "--force"), {"action": "store_true"})
ARG_BVID = (("-b", "--bvid"), {})
ARG_UP_MID = (("-u", "--up-mid"), {"type": int})
ARG_GROUP = (("-g", "--group"), {"action": "append"})
ARG_MAX_PAGES = (("-p", "--max-pages"), {})
ARG_MIN_DURATION = (("-d", "--min-duration"), {})
ARG_WAIT = (("-n", "--no-wait"), {"action": "store_false", "dest": "wait", "default": True, "help": "不等待任务完成直接退出"})
ARG_SKIP_SCAN = (("-s", "--skip-scan"), {"action": "store_true", "help": "跳过扫描步骤"})
ARG_SERVER_ID = (("-s", "--server-id"), {})
ARG_MAX_DURATION = (("-d", "--max-duration"), {})
ARG_CLAIM_TIMEOUT = (("-t", "--claim-timeout-minutes"), {})
ARG_KEEP_LOCAL = (("-k", "--keep-local-result"), {"action": "store_true"})
ARG_MAX_TASKS = (("-m", "--max-tasks"), {})
ARG_INTERVAL = (("-i", "--interval"), {})
ARG_VIDEO = ("video", {})
ARG_MESSAGE = (("-m", "--message"), {})
ARG_DRY_RUN = (("-d", "--dry-run"), {"action": "store_true"})
ARG_FILE = ("file", {})
ARG_KEEP = (("-k", "--keep"), {"action": "store_true"})
ARG_LIMIT = (("-l", "--limit"), {})
ARG_BVID_REQUIRED = (("-b", "--bvid"), {"required": True})
ARG_AI = (("-a", "--ai"), {})
ARG_LIST = (("-l", "--list"), {"action": "store_true"})
ARG_NAME = (("-n", "--name"), {})
ARG_STOCK = (("-s", "--stock"), {"action": "store_true"})
ARG_MODEL = (("-m", "--model"), {})
ARG_SOURCE_DB = ("source_db", {})
ARG_TARGET_DB = ("target_db", {})

_SERVER_ARGS = [ARG_SERVER_ID, ARG_MAX_DURATION, ARG_CLAIM_TIMEOUT, ARG_KEEP_LOCAL, ARG_MAX_TASKS, ARG_INTERVAL]
_SCAN_ARGS = [ARG_UP_MID, ARG_GROUP, ARG_MAX_PAGES]
_RENDER_ARGS = [ARG_FORCE, ARG_BVID]

# ---------------------------------------------------------------------------
# Command registry: role -> [(command_name, handler, [arg_specs])]
# ---------------------------------------------------------------------------
COMMANDS = {
    "init": [
        ("data", init_data, []),
        ("queue", init_queue, []),
    ],
    "client": [
        ("scan", client_scan, _SCAN_ARGS),
        ("submit", client_submit, [ARG_INPUT]),
        ("prepare-audio", client_prepare_audio, [ARG_MIN_DURATION]),
        ("collect", client_collect, [ARG_FORCE]),
        ("render", client_render, _RENDER_ARGS),
        ("sync", client_sync, [ARG_FORCE]),
        ("run", client_run, _SCAN_ARGS + [ARG_INPUT, ARG_MIN_DURATION, ARG_WAIT, ARG_FORCE, ARG_BVID, ARG_SKIP_SCAN]),
        ("resubmit-missing", client_resubmit_missing, [ARG_INPUT]),
        ("finish", client_finish, [ARG_MESSAGE]),
    ],
    "server": [
        ("claim", server_claim, _SERVER_ARGS),
        ("transcribe", server_transcribe, _SERVER_ARGS),
        ("publish", server_publish, _SERVER_ARGS),
        ("once", server_once, _SERVER_ARGS),
        ("run", server_run, _SERVER_ARGS),
        ("release-claimed", server_release_claimed, _SERVER_ARGS),
    ],
    "admin": [
        ("check-missing", admin_check_missing, []),
        ("check-ai", admin_check_ai, [ARG_LIST, ARG_NAME, ARG_STOCK, ARG_MODEL]),
        ("fix-summaries", admin_fix_summaries, [ARG_LIMIT, ARG_BVID]),
        ("webdav-clean", admin_webdav_clean, [ARG_DRY_RUN]),
        ("webdav-upload", admin_webdav_upload, [ARG_FILE, ARG_KEEP]),
        ("download-audio", admin_download_audio, [ARG_VIDEO]),
        ("download-audio-upload", admin_download_audio_upload, [ARG_VIDEO]),
        ("push-data", admin_push_data, [ARG_MESSAGE]),
        ("resummarize", admin_resummarize, [ARG_BVID_REQUIRED, ARG_AI]),
        ("migrate-main-db", admin_migrate_main_db, [ARG_SOURCE_DB, ARG_TARGET_DB, ARG_DRY_RUN]),
    ],
}


def _is_git_repo(path: Path) -> bool:
    try:
        import git
        git.Repo(path)
        return True
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(line_buffering=True)
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(line_buffering=True)
        except Exception:
            pass

    _fix_windows_home()
    parser = build_parser()
    args = parser.parse_args(argv)

    command_name = " ".join(part for part in (getattr(args, "role", None), getattr(args, "command", None)) if part)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 2

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    if args.role == "client":
        data_ok = _is_git_repo(config.data_dir)
        queue_ok = _is_git_repo(config.queue_dir)
        if not data_ok or not queue_ok:
            if not data_ok:
                print(f"错误: data 目录 ({config.data_dir}) 不是 Git 仓库。请运行: python b2t.py init data", file=sys.stderr)
            if not queue_ok:
                print(f"错误: queue 目录 ({config.queue_dir}) 不是 Git 仓库。请运行: python b2t.py init queue", file=sys.stderr)
            return 1
    elif args.role == "server":
        if not _is_git_repo(config.queue_dir):
            print(f"错误: queue 目录 ({config.queue_dir}) 不是 Git 仓库。请 clone queue 目录后再运行", file=sys.stderr)
            return 1

    logger = setup_logger(command_name.replace(" ", "_"), config.logs_dir)
    log_command_start(logger, command_name, config.config_path)
    logger.info("Data repo: %s", config.data_dir)
    logger.info("Queue repo: %s", config.queue_dir)
    logger.info("Temp dir: %s", config.temp_dir)

    ctx = CommandContext(config=config, command_name=command_name)

    try:
        result = args.handler(ctx, args, logger)
    except NotImplementedError as exc:
        logger.error("%s", exc)
        result = 2
    except InitError as exc:
        logger.error("Command failed: %s", exc)
        result = 1
    except Exception as exc:
        logger.exception("Command failed: %s", exc)
        result = 1

    log_command_finish(logger, command_name, failed=1 if result else 0)
    return int(result or 0)


COMMAND_HELPS = {
    "init": {
        "data": "初始化本地数据仓库（创建目录结构、数据库和配置文件）",
        "queue": "初始化共享任务队列仓库（创建队列目录结构）",
    },
    "client": {
        "scan": "扫描关注的 UP 主，检查是否有新发布的视频",
        "submit": "将新视频打包成转写任务提交到 Git 任务队列中",
        "prepare-audio": "提取视频音频并上传至共享 WebDAV 网盘",
        "collect": "从任务队列拉取已转写完成的 JSON 结果",
        "render": "将收集到的转写结果渲染并调用 AI 生成 Markdown 总结",
        "sync": "将生成的 Markdown 总结同步至网盘或指定归档目录",
        "run": "一键自动执行上述整套本地客户端流程",
        "resubmit-missing": "重新提交失败或丢失的任务至队列",
        "finish": "提交并推送本地 data 数据仓库中的所有更改至远程 Git 仓库备份",
    },
    "server": {
        "claim": "认领队列中的待转写任务",
        "transcribe": "下载音频并使用 Whisper 执行语音转文字",
        "publish": "将转写结果以 JSON 格式提交到队列并标记已完成",
        "once": "执行一次认领、转写和发布流程",
        "run": "后台循环运行认领、转写和发布流程",
        "release-claimed": "释放队列中指定服务节点超时过期的被占用任务",
    },
    "admin": {
        "check-missing": "检查是否存在已分配但未成功转写或存在遗漏的任务",
        "check-ai": "运行 AI 服务可用性自检与可用模型/配额测试",
        "fix-summaries": "修复或重新生成本地总结失败的 Markdown 文本",
        "migrate-main-db": "将 main 分支旧 videos SQLite 数据库迁移到 dev 新数据库结构",
        "webdav-clean": "清理 WebDAV 云盘中过期的临时音频文件",
        "webdav-upload": "手动上传特定音频文件到 WebDAV 缓存",
        "download-audio": "手动下载特定视频的音频文件到本地",
        "download-audio-upload": "手动下载特定视频音频并上传至 WebDAV",
        "push-data": "手动将本地的 data 数据推送到绑定的远程 Git 仓库备份",
        "resummarize": "针对特定 BV 号视频重新生成 AI 总结",
    },
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="b2t")
    parser.add_argument("--config", help="Path to config YAML")
    subparsers = parser.add_subparsers(dest="role", help="运行角色")

    role_helps = {
        "init": "初始化相关命令（创建目录结构、关联 Git 仓库等）",
        "client": "客户端/本地控制端流程（扫描、提交、收集、渲染、同步等）",
        "server": "转写节点/服务端流程（认领、转写、发布等）",
        "admin": "管理员工具（检查、重试、AI诊断、WebDAV清理等）",
    }

    for role_name, command_list in COMMANDS.items():
        role_parser = subparsers.add_parser(role_name, help=role_helps.get(role_name))
        commands = role_parser.add_subparsers(dest="command", help="子命令")
        for cmd_name, handler, arg_specs in command_list:
            help_text = COMMAND_HELPS.get(role_name, {}).get(cmd_name, "")
            _register(commands, cmd_name, handler, arg_specs, help_text)

    return parser


def _register(commands, name: str, handler, arg_specs: list, help_text: str = "") -> None:
    parser = commands.add_parser(name, help=help_text)
    seen: set[str] = set()
    for flag_or_flags, kwargs in arg_specs:
        if isinstance(flag_or_flags, str):
            flags = (flag_or_flags,)
        else:
            flags = flag_or_flags
        main_flag = flags[-1]
        if main_flag in seen:
            continue
        seen.add(main_flag)
        parser.add_argument(*flags, **kwargs)
    parser.set_defaults(handler=handler)


def _fix_windows_home() -> None:
    if os.name == "nt" and not os.environ.get("HOME"):
        os.environ["HOME"] = os.environ.get("USERPROFILE", "")


if __name__ == "__main__":
    raise SystemExit(main())
