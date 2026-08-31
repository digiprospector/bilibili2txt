from __future__ import annotations

import logging
from typing import Any

from ..config import CommandContext
from ..services.git_helpers import commit_all, open_repo, push_and_check
from .init import _prepare_repo, _commit_repo, _push_initial_main


def init(ctx: CommandContext, _args: Any, logger: logging.Logger) -> int:
    """初始化 Hugo 静态网站独立仓库"""
    site_dir = ctx.config.site_dir
    _prepare_repo(site_dir, "site", logger)
    hugo = ctx.hugo_site(logger)
    hugo.ensure_layout()
    _commit_repo(site_dir, "init hugo site repo", logger)
    _push_initial_main(site_dir, "site", logger)
    logger.info("Hugo 独立站点仓库初始化完成: %s", site_dir)
    return 0


def sync(ctx: CommandContext, args: Any, logger: logging.Logger) -> int:
    """将 Markdown 笔记转换为 Hugo 文章并同步到 site 目录"""
    force = getattr(args, "force", False)
    bvid = getattr(args, "bvid", None)
    hugo = ctx.hugo_site(logger)
    stats = hugo.sync_markdown(force=force, bvid=bvid)
    logger.info(
        "Hugo 同步完成: 共扫描 %d 篇, 新同步/更新 %d 篇, 跳过 %d 篇, 失败 %d 篇",
        stats.total,
        stats.synced,
        stats.skipped,
        stats.failed,
    )
    return 0 if stats.failed == 0 else 1


def build(ctx: CommandContext, args: Any, logger: logging.Logger) -> int:
    """同步 Markdown 并执行本地 Hugo 静态构建"""
    sync_res = sync(ctx, args, logger)
    if sync_res != 0:
        return sync_res

    hugo = ctx.hugo_site(logger)
    if not hugo.is_hugo_installed():
        logger.info("同步完成。本地未安装 Hugo，无需本地构建。可直接执行 'push' 命令推送到 GitHub 触发自动构建。")
        return 0

    success = hugo.build_locally()
    return 0 if success else 1


def preview(ctx: CommandContext, args: Any, logger: logging.Logger) -> int:
    """同步 Markdown 并启动 Hugo 本地预览服务器"""
    sync_res = sync(ctx, args, logger)
    if sync_res != 0:
        return sync_res

    port = getattr(args, "port", 1313) or 1313
    hugo = ctx.hugo_site(logger)
    hugo.preview_locally(port=int(port))
    return 0


def push(ctx: CommandContext, args: Any, logger: logging.Logger) -> int:
    """提交并推送 Hugo 站点内容到远程 Git 仓库"""
    message = getattr(args, "message", None) or "update site content"
    site_dir = ctx.config.site_dir
    repo = open_repo(site_dir)
    
    committed = commit_all(repo, message, logger)
    if not committed and not repo.is_dirty(untracked_files=True):
        logger.info("没有需要推送的更改")
    
    try:
        origin = repo.remotes.origin
    except AttributeError as exc:
        logger.error("未配置远程 origin 仓库: %s", exc)
        return 1

    logger.info("正在推送站点更新至 GitHub: %s", origin.url)
    push_and_check(origin)
    logger.info("站点更新已成功推送！GitHub Actions 将自动执行构建与部署。")
    return 0
