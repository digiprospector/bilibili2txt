from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import git
import yaml

from .git_helpers import commit_all, open_repo, push_and_check

if TYPE_CHECKING:
    from ..config import AppConfig

# 匹配形如 [2026-08-27_19-55-46][UP主][标题][BV1xxx].md 或 .text 的文件名
FILENAME_PATTERN = re.compile(r"^\[(.*?)\]\[(.*?)\]\[(.*?)\]\[(.*?)\]\.(?:md|text)$")

# 时区常量（默认使用北京时间 UTC+8）
CST = timezone(timedelta(hours=8))


@dataclass
class HugoSyncStats:
    synced: int = 0
    skipped: int = 0
    failed: int = 0
    total: int = 0


@dataclass
class MarkdownDocMeta:
    filename: str
    timestamp_raw: str
    up_name: str
    title: str
    bvid: str
    date_folder: str
    iso_date: str


def parse_markdown_filename(path: Path) -> MarkdownDocMeta | None:
    """解析 Markdown 文件名获取元数据"""
    match = FILENAME_PATTERN.match(path.name)
    if not match:
        return None
    timestamp_raw, up_name, title, bvid = match.groups()
    date_part, _, time_part = timestamp_raw.partition("_")
    
    # 格式化为 ISO 8601 时间格式 (YYYY-MM-DDTHH:MM:SS+08:00)
    if time_part:
        time_formatted = time_part.replace("-", ":")
        iso_str = f"{date_part}T{time_formatted}+08:00"
    else:
        iso_str = f"{date_part}T00:00:00+08:00"

    return MarkdownDocMeta(
        filename=path.name,
        timestamp_raw=timestamp_raw,
        up_name=up_name,
        title=title,
        bvid=bvid,
        date_folder=date_part,
        iso_date=iso_str,
    )


def extract_summary_preview(content: str, max_chars: int = 160) -> str:
    """从 Markdown 正文中提取 AI 总结的前几句作为列表摘要"""
    ai_summary_match = re.search(r"## AI总结\s+(?:>.*?\n\s*)?(.*?)(?=## 视频文稿|$)", content, re.DOTALL)
    if ai_summary_match:
        text = ai_summary_match.group(1).strip()
        # 清除 markdown 标记如 #, *, -, ` 等
        clean = re.sub(r"[#*`>_\-\[\]]", "", text)
        clean = re.sub(r"\s+", " ", clean).strip()
        if len(clean) > max_chars:
            return clean[:max_chars] + "..."
        return clean
    return ""


def clean_markdown_body(content: str, title: str) -> str:
    """清理 Markdown 正文，移除开头的重复 H1 标题"""
    lines = content.splitlines()
    start_idx = 0
    # 跳过开头空白
    while start_idx < len(lines) and not lines[start_idx].strip():
        start_idx += 1
    # 如果第一行是 # 标题，则跳过
    if start_idx < len(lines) and lines[start_idx].startswith("# ") and title in lines[start_idx]:
        start_idx += 1
        while start_idx < len(lines) and not lines[start_idx].strip():
            start_idx += 1
    return "\n".join(lines[start_idx:]).strip()


def build_hugo_front_matter(meta: MarkdownDocMeta, content: str) -> str:
    """生成 Hugo PaperMod 兼容的 YAML Front Matter"""
    summary = extract_summary_preview(content)
    
    # 构造安全标题（去除反斜杠和多余引号）
    safe_title = meta.title.replace('"', '\\"').replace("\n", " ").strip()
    safe_up = meta.up_name.replace('"', '\\"').strip()
    safe_summary = summary.replace('"', '\\"').strip()
    
    front_matter_dict: dict[str, Any] = {
        "title": safe_title,
        "date": meta.iso_date,
        "lastmod": meta.iso_date,
        "author": [safe_up],
        "categories": [safe_up],
        "tags": [safe_up],
        "params": {
            "bvid": meta.bvid,
            "video_url": f"https://www.bilibili.com/video/{meta.bvid}",
            "up_name": safe_up,
        },
        "summary": safe_summary,
        "showToc": True,
        "TocOpen": False,
        "draft": False,
    }
    
    yaml_str = yaml.dump(front_matter_dict, allow_unicode=True, sort_keys=False)
    return f"---\n{yaml_str}---\n\n"


DEFAULT_HUGO_TOML = """baseURL = '{base_url}'
languageCode = 'zh-cn'
defaultContentLanguage = 'zh-cn'
title = '{title}'
theme = '{theme}'

[pagination]
pagerSize = 15

[enableRobotsTXT]
enable = true
buildDrafts = false
buildFuture = false
buildExpired = false

[minify]
disableXML = false
minifyOutput = true

[params]
env = 'production'
title = '{title}'
description = 'B站关注UP主视频文稿与 AI 智能总结归档'
keywords = ['bilibili', 'AI总结', '转录', '笔记', '视频文稿']
author = '{author}'
ShowReadingTime = true
ShowShareButtons = false
ShowPostNavLinks = true
ShowBreadCrumbs = true
ShowCodeCopyButtons = true
ShowWordCount = true
ShowRssButtonInSectionTermList = true
UseHugoToc = true
disableSpecial1stPost = false
disableScrollToTop = false
comments = false
hidemeta = false
hideSummary = false
showtoc = true
tocopen = false

[params.homeInfoParams]
Title = "📺 {title}"
Content = "自动收集并转写关注 UP 主的最新视频，使用大模型提取核心要点与结构化总结。"

[[params.socialIcons]]
name = "bilibili"
url = "https://space.bilibili.com"

[[params.socialIcons]]
name = "github"
url = "https://github.com/digiprospector/bilibili2txt"

[params.fuseOpts]
isCaseSensitive = false
shouldSort = true
location = 0
distance = 1000
threshold = 0.4
minMatchCharLength = 2
keys = ["title", "permalink", "summary", "content"]

[menu]
[[menu.main]]
identifier = "search"
name = "🔍 搜索"
url = "/search/"
weight = 10

[[menu.main]]
identifier = "categories"
name = "👤 UP主"
url = "/categories/"
weight = 20

[[menu.main]]
identifier = "archives"
name = "📅 归档"
url = "/archives/"
weight = 30

[outputs]
home = ["HTML", "RSS", "JSON"]
"""

SEARCH_MD_CONTENT = """---
title: "搜索"
layout: "search"
summary: "search"
placeholder: "搜索视频标题、UP主、AI总结或正文内容..."
---
"""

ARCHIVES_MD_CONTENT = """---
title: "归档"
layout: "archives"
url: "/archives/"
summary: "archives"
---
"""

GITHUB_ACTIONS_WORKFLOW = """name: Deploy Hugo site to Pages

on:
  push:
    branches:
      - main
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

defaults:
  run:
    shell: bash

jobs:
  build:
    runs-on: ubuntu-latest
    env:
      HUGO_VERSION: 0.128.0
    steps:
      - name: Install Hugo CLI
        run: |
          wget -O ${{ runner.temp }}/hugo.deb https://github.com/gohugoio/hugo/releases/download/v${{ env.HUGO_VERSION }}/hugo_extended_${{ env.HUGO_VERSION }}_linux-amd64.deb \\
          && sudo dpkg -i ${{ runner.temp }}/hugo.deb
      - name: Checkout
        uses: actions/checkout@v4
        with:
          submodules: recursive
          fetch-depth: 0
      - name: Setup Pages
        id: pages
        uses: actions/configure-pages@v5
      - name: Build with Hugo
        env:
          HUGO_CACHEDIR: ${{ runner.temp }}/hugo_cache
          HUGO_ENVIRONMENT: production
        run: |
          hugo \\
            --gc \\
            --minify \\
            --baseURL "${{ steps.pages.outputs.base_url }}/"
      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: ./public

  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    needs: build
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
"""

SITE_GITIGNORE = """# Hugo 产物与缓存
public/
resources/
.hugo_build.lock

# 系统文件
.DS_Store
Thumbs.db
"""


class HugoSite:
    """Hugo 静态站点管理服务"""

    def __init__(
        self,
        site_root: Path,
        markdown_root: Path,
        config: AppConfig,
        logger: logging.Logger,
    ):
        self.site_root = site_root
        self.markdown_root = markdown_root
        self.config = config
        self.logger = logger

    @property
    def content_posts_dir(self) -> Path:
        return self.site_root / "content" / "posts"

    def ensure_layout(self) -> None:
        """确保 Hugo 站点的目录与基础配置文件完整"""
        self.site_root.mkdir(parents=True, exist_ok=True)
        self.content_posts_dir.mkdir(parents=True, exist_ok=True)
        (self.site_root / "static").mkdir(parents=True, exist_ok=True)
        (self.site_root / "layouts").mkdir(parents=True, exist_ok=True)
        (self.site_root / "archetypes").mkdir(parents=True, exist_ok=True)
        (self.site_root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)

        # 写入 hugo.toml
        hugo_toml_path = self.site_root / "hugo.toml"
        if not hugo_toml_path.exists():
            base_url = self.config.get("site.base_url", "https://example.github.io/bilibili-notes/")
            title = self.config.get("site.title", "Bilibili 视频笔记与 AI 总结")
            author = self.config.get("site.author", "bilibili2txt")
            theme = self.config.get("site.theme", "PaperMod")
            content = DEFAULT_HUGO_TOML.format(
                base_url=base_url,
                title=title,
                author=author,
                theme=theme,
            )
            hugo_toml_path.write_text(content, encoding="utf-8")
            self.logger.info("创建 Hugo 配置文件：%s", hugo_toml_path)

        # 写入 content/search.md 与 content/archives.md
        search_md = self.site_root / "content" / "search.md"
        if not search_md.exists():
            search_md.write_text(SEARCH_MD_CONTENT, encoding="utf-8")
            self.logger.info("创建搜索页面：%s", search_md)

        archives_md = self.site_root / "content" / "archives.md"
        if not archives_md.exists():
            archives_md.write_text(ARCHIVES_MD_CONTENT, encoding="utf-8")
            self.logger.info("创建归档页面：%s", archives_md)

        # 写入 GitHub Actions workflow
        workflow_path = self.site_root / ".github" / "workflows" / "deploy.yml"
        if not workflow_path.exists():
            workflow_path.write_text(GITHUB_ACTIONS_WORKFLOW, encoding="utf-8")
            self.logger.info("创建 GitHub Actions 部署工作流：%s", workflow_path)

        # 写入 .gitignore
        site_gitignore = self.site_root / ".gitignore"
        if not site_gitignore.exists():
            site_gitignore.write_text(SITE_GITIGNORE, encoding="utf-8")
            self.logger.info("创建站点 .gitignore：%s", site_gitignore)

        # 确保主题 PaperMod 存在
        self._ensure_theme()

    def _ensure_theme(self) -> None:
        """检查并确保 PaperMod 主题存在"""
        theme_dir = self.site_root / "themes" / "PaperMod"
        if theme_dir.exists() and any(theme_dir.iterdir()):
            return

        self.logger.info("正在拉取 PaperMod 主题到 %s ...", theme_dir)
        theme_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            # 尝试通过 git clone 拉取主题
            git.Repo.clone_from(
                "https://github.com/adityatelange/hugo-PaperMod.git",
                theme_dir,
                depth=1,
            )
            self.logger.info("成功拉取 PaperMod 主题")
        except Exception as exc:
            self.logger.warning("拉取 PaperMod 主题失败（若在 GitHub Actions 构建则会自动拉取）：%s", exc)

    def sync_markdown(self, force: bool = False, bvid: str | None = None) -> HugoSyncStats:
        """扫描 data/markdown/ 并转换同步为带 Front Matter 的 Hugo 文章"""
        stats = HugoSyncStats()
        if not self.markdown_root.exists():
            self.logger.warning("Markdown 源目录不存在：%s", self.markdown_root)
            return stats

        self.ensure_layout()

        # 遍历所有日期目录
        day_dirs = sorted(
            [d for d in self.markdown_root.iterdir() if d.is_dir()],
            key=lambda x: x.name,
            reverse=True,
        )

        for day_dir in day_dirs:
            for md_file in sorted(day_dir.glob("*.md")):
                stats.total += 1
                if bvid and bvid not in md_file.name:
                    continue

                meta = parse_markdown_filename(md_file)
                if not meta:
                    self.logger.warning("跳过无法解析文件名的 Markdown：%s", md_file.name)
                    stats.failed += 1
                    continue

                # 目标文件名与路径
                target_day_dir = self.content_posts_dir / meta.date_folder
                target_day_dir.mkdir(parents=True, exist_ok=True)
                # 使用标题和 BV 号生成干净的目标文件名
                clean_filename = f"{meta.title}_{meta.bvid}.md"
                # 清除文件名中的非法字符
                clean_filename = re.sub(r'[\\/*?:"<>|]', "", clean_filename)
                target_path = target_day_dir / clean_filename

                # 判断是否需要更新
                if target_path.exists() and not force:
                    # 如果目标文件比源文件新，且非空，则跳过
                    if target_path.stat().st_mtime >= md_file.stat().st_mtime and target_path.stat().st_size > 0:
                        stats.skipped += 1
                        continue

                try:
                    raw_content = md_file.read_text(encoding="utf-8")
                    front_matter = build_hugo_front_matter(meta, raw_content)
                    clean_body = clean_markdown_body(raw_content, meta.title)
                    hugo_article_content = f"{front_matter}{clean_body}\n"

                    target_path.write_text(hugo_article_content, encoding="utf-8")
                    self.logger.info("已同步 Hugo 文章：%s -> %s", md_file.name, target_path.name)
                    stats.synced += 1
                except Exception as exc:
                    self.logger.error("同步文件失败 %s: %s", md_file, exc)
                    stats.failed += 1

        return stats

    def is_hugo_installed(self) -> bool:
        """检查本机是否安装了 hugo CLI"""
        return shutil.which("hugo") is not None

    def build_locally(self) -> bool:
        """在本地调用 hugo CLI 进行构建"""
        if not self.is_hugo_installed():
            self.logger.warning("本地未检测到 hugo 可执行文件。")
            self.logger.info("提示：您可以直接推送仓库到 GitHub，由 GitHub Actions 自动云端构建。")
            self.logger.info("若需本地构建与预览，可通过命令安装：winget install Hugo.Hugo.Extended")
            return False

        self.logger.info("正在执行 Hugo 本地构建...")
        try:
            result = subprocess.run(
                ["hugo", "--minify"],
                cwd=str(self.site_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            if result.returncode == 0:
                self.logger.info("Hugo 本地构建成功！静态文件输出到：%s", self.site_root / "public")
                return True
            else:
                self.logger.error("Hugo 构建失败：%s", result.stderr)
                return False
        except Exception as exc:
            self.logger.error("执行 hugo 命令异常：%s", exc)
            return False

    def preview_locally(self, port: int = 1313) -> None:
        """在本地启动 Hugo 开发预览服务器"""
        if not self.is_hugo_installed():
            self.logger.warning("本地未检测到 hugo 可执行文件，无法启动本地预览。")
            self.logger.info("若需本地预览，请先安装 Hugo：winget install Hugo.Hugo.Extended")
            return

        self.logger.info("正在启动 Hugo 本地预览服务器 (http://localhost:%d)... 按 Ctrl+C 停止", port)
        try:
            subprocess.run(
                ["hugo", "server", "-D", "-p", str(port)],
                cwd=str(self.site_root),
                check=False,
            )
        except KeyboardInterrupt:
            self.logger.info("Hugo 预览已停止")
