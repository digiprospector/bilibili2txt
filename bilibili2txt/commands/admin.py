from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import CommandContext
from ..database import migrate_main_database
from ..models import Task
from ..services.audio import AudioService
from ..services.bilibili import BilibiliService
from ..services.ai import AIService
from ..services.gitrepo import GitRepo
from ..services.webdav import WebDavClient
from ..services.video_id import parse_video_input
from ..services.markdown import render_or_update_summary


def check_missing(ctx: CommandContext, _args, logger: logging.Logger) -> int:
    submitted_dir = ctx.config.data_dir / "tasks" / "submitted"
    save_dir = ctx.config.data_dir / "save"
    output_dir = ctx.config.temp_dir / "missing_tasks"
    output_dir.mkdir(parents=True, exist_ok=True)

    text_names = [path.name for path in save_dir.glob("*.text")] if save_dir.exists() else []
    missing = 0
    checked = 0
    for task_file in sorted(submitted_dir.glob("*.json")):
        task = Task.from_file(task_file)
        if task.status != "normal":
            logger.info("跳过非 normal 状态的已提交任务: %s status=%s", task.task_id, task.status)
            continue
        checked += 1
        if any(task.bvid in name for name in text_names):
            continue
        target = output_dir / task_file.name
        shutil.copy2(task_file, target)
        logger.info("已导出丢失的任务: %s -> %s", task_file, target)
        missing += 1

    logger.info("检查丢失任务总结: 已检查=%s 丢失=%s", checked, missing)
    return 0


def webdav_upload(ctx: CommandContext, args, logger: logging.Logger) -> int:
    file_path = Path(args.file).resolve()
    if not file_path.is_file():
        logger.error("不是文件: %s", file_path)
        return 1
    client = WebDavClient.from_config(ctx.config, logger)
    if not client.upload(file_path, show_progress=True):
        return 1
    if not args.keep:
        file_path.unlink()
        logger.info("上传后删除了本地文件: %s", file_path)
    return 0


def webdav_clean(ctx: CommandContext, args, logger: logging.Logger) -> int:
    client = WebDavClient.from_config(ctx.config, logger)
    files = _list_webdav_files(client, logger)
    logger.info("待删除的 WebDAV 文件数: %s", len(files))
    failed = 0
    for name in files:
        logger.info("WebDAV 清理目标: %s", name)
        if args.dry_run:
            continue
        if not client.delete(name):
            failed += 1
    logger.info("WebDAV 清理总结: 总数=%s 失败=%s dry_run=%s", len(files), failed, args.dry_run)
    return 0 if failed == 0 else 1


def push_data(ctx: CommandContext, args, logger: logging.Logger) -> int:
    repo = GitRepo(ctx.config.data_dir, logger)
    message = args.message or "update"
    repo.commit_and_push_all(message)
    return 0


def migrate_main_db(_ctx: CommandContext, args, logger: logging.Logger) -> int:
    stats = migrate_main_database(Path(args.source_db), Path(args.target_db), dry_run=args.dry_run)
    logger.info(
        "迁移主数据库总结: 已读取=%s 已插入=%s 已更新=%s dry_run=%s",
        stats["read"],
        stats["inserted"],
        stats["updated"],
        args.dry_run,
    )
    return 0


def _list_webdav_files(client: WebDavClient, logger: logging.Logger) -> list[str]:
    import xml.etree.ElementTree as ET
    import requests

    response = requests.request(
        "PROPFIND",
        client.base_url,
        auth=(client.username, client.password),
        headers={"Depth": "1"},
        timeout=30,
        proxies=client.proxies,
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)
    ns = {"d": "DAV:"}
    files: list[str] = []
    for href in root.findall(".//d:href", ns):
        text = href.text or ""
        if text.endswith("/"):
            continue
        files.append(Path(text).name)
    logger.info("已列出 WebDAV 文件数: %s", len(files))
    return files


def check_ai(ctx: CommandContext, args, logger: logging.Logger) -> int:
    service = AIService(ctx.config, logger)
    providers = service.providers()
    if args.list:
        for provider in providers:
            logger.info(
                "AI 服务商: name=%s model=%s base_url=%s",
                provider.get("name"),
                provider.get("model"),
                provider.get("base_url"),
            )
        return 0

    if args.name:
        providers = [provider for provider in providers if provider.get("name") == args.name]
    if not providers:
        logger.error("没有匹配的 AI 服务商")
        return 1

    success_count = 0
    for provider in providers:
        ok, message = service.test_provider(provider)
        if ok:
            success_count += 1
            logger.info("AI 测试成功: %s", message)
        else:
            logger.error("AI 测试失败: %s", message)
    return 0 if success_count else 1


def fix_summaries(_ctx: CommandContext, _args, _logger: logging.Logger) -> int:
    ctx = _ctx
    args = _args
    logger = _logger
    ai = AIService(ctx.config, logger)
    save_dir = ctx.config.data_dir / "save"
    markdown_root = ctx.config.data_dir / "markdown"
    text_files = sorted(save_dir.glob("*.text"))
    if args.bvid:
        text_files = [path for path in text_files if args.bvid in path.name]
    if args.limit:
        text_files = text_files[: int(args.limit)]

    succeeded = 0
    failed = 0
    for text_file in text_files:
        try:
            result = render_or_update_summary(text_file, markdown_root, ai, logger)
            if result:
                logger.info("已修复总结: %s", result[0])
                succeeded += 1
        except Exception as exc:
            logger.error("为 %s 修复总结失败: %s", text_file, exc)
            failed += 1
    _sync_netdisk_best_effort(ctx, logger)
    logger.info("修复总结汇总: 成功=%s 失败=%s", succeeded, failed)
    return 0 if failed == 0 else 1


def _download_audio_impl(ctx: CommandContext, args, logger: logging.Logger, *, upload: bool) -> int:
    task = _task_from_video_arg(ctx, args.video, logger)
    if not task:
        return 1
    audio = AudioService(ctx.config, logger)
    files = audio.download_task_audio(task)
    if upload:
        return 0 if audio.upload_task_audio(task, files) else 1
    for f in files:
        logger.info("已下载音频: %s", f)
    return 0


def download_audio(ctx: CommandContext, args, logger: logging.Logger) -> int:
    return _download_audio_impl(ctx, args, logger, upload=False)


def download_audio_upload(ctx: CommandContext, args, logger: logging.Logger) -> int:
    return _download_audio_impl(ctx, args, logger, upload=True)


def resummarize(ctx: CommandContext, args, logger: logging.Logger) -> int:
    save_dir = ctx.config.data_dir / "save"
    text_files = [path for path in save_dir.glob("*.text") if args.bvid in path.name]
    if not text_files:
        logger.error("未找到 BVID %s 的文稿", args.bvid)
        return 1
    text_file = text_files[0]
    markdown_root = ctx.config.data_dir / "markdown"
    ai = AIService(ctx.config, logger)
    try:
        result = render_or_update_summary(text_file, markdown_root, ai, logger, force=True)
        if result:
            logger.info("已重新生成 Markdown: %s", result[0])
    except Exception as exc:
        logger.error("AI 重新总结失败: %s", exc)
        return 1
    _sync_netdisk_best_effort(ctx, logger)
    return 0


def _sync_netdisk_best_effort(ctx: CommandContext, logger: logging.Logger) -> None:
    try:
        service = ctx.netdisk_sync(logger)
        stats = service.sync(force=True)
        logger.info("更新总结后的网盘同步状态: %s", stats)
    except Exception as exc:
        logger.warning("更新总结后的网盘同步被跳过或失败: %s", exc)


def _task_from_video_arg(ctx: CommandContext, value: str, logger: logging.Logger) -> Task | None:
    bvid, aid = parse_video_input(value)
    if not bvid and aid is None:
        logger.error("无法解析视频输入参数: %s", value)
        return None
    service = BilibiliService(ctx.config, logger)
    if not service.login():
        logger.error("Bilibili 登录失败")
        return None
    info = service.get_video_detail(bvid=bvid, aid=aid)
    info.setdefault("aid", aid)
    return Task.from_bilibili_info(info)
