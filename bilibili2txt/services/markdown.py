from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ai import AIService


FILENAME_PATTERN = re.compile(r"\[(.*?)\]\[(.*?)\]\[(.*?)\]\[(.*?)\]\.text$")


@dataclass
class TranscriptMetadata:
    filename: str
    timestamp: str
    up_name: str
    title: str
    bvid: str
    date_folder: str
    formatted_time: str


def parse_transcript_filename(path: Path) -> TranscriptMetadata | None:
    match = FILENAME_PATTERN.match(path.name)
    if not match:
        return None
    timestamp, up_name, title, bvid = match.groups()
    date_part, _, time_part = timestamp.partition("_")
    formatted_time = f"{date_part} {time_part.replace('-', ':')}" if time_part else timestamp
    return TranscriptMetadata(
        filename=path.name,
        timestamp=timestamp,
        up_name=up_name,
        title=title,
        bvid=bvid,
        date_folder=date_part,
        formatted_time=formatted_time,
    )


def _sanitize_dirname(value: str) -> str:
    invalid = '<>:"/\\|?*'
    cleaned = value.translate(str.maketrans(invalid, "_" * len(invalid))).strip().rstrip(". ")
    return cleaned or "untitled"


def md_path_for(
    meta: TranscriptMetadata,
    markdown_root: Path,
    text_file: Path,
    source_type: str = "group",
    category: str = "投资",
    dir_title: str | None = None,
) -> Path:
    if source_type == "manual":
        title_dir = _sanitize_dirname(dir_title or meta.title)
        return markdown_root / "manual" / category / title_dir / text_file.with_suffix(".md").name
    return markdown_root / meta.date_folder / text_file.with_suffix(".md").name


def video_url_for(bvid: str) -> str:
    match = re.fullmatch(r"(?i)(BV[a-zA-Z0-9]{10})_p([0-9]+)", bvid.strip())
    if match:
        return f"https://www.bilibili.com/video/{match.group(1)}?p={match.group(2)}"
    return f"https://www.bilibili.com/video/{bvid}"

def adjust_heading_levels(summary: str) -> str:
    headings = re.findall(r"(?m)^(#+)[ \t]+", summary)
    if not headings:
        return summary

    levels = [len(h) for h in headings]
    highest_level = min(levels)
    shift = 3 - highest_level
    if shift == 0:
        return summary

    def replace_heading(match: re.Match) -> str:
        hashes = match.group(1)
        new_len = len(hashes) + shift
        new_len = max(1, new_len)
        return "#" * new_len + " "

    return re.sub(r"(?m)^(#+)[ \t]+", replace_heading, summary)


def build_markdown(
    meta: TranscriptMetadata,
    transcript: str,
    summary: str,
    ai_provider: str,
    source_type: str = "group",
    category: str = "投资",
    video_url: str | None = None,
) -> str:
    summary = adjust_heading_levels(summary)
    source_label = "手动添加 (Manual)" if source_type == "manual" else "自动同步 (Auto)"
    tag_source = "手动添加" if source_type == "manual" else "自动同步"
    resolved_url = video_url or video_url_for(meta.bvid)
    return f"""# {meta.title}

- **分类**: {category}
- **来源**: {source_label}
- **UP主**: {meta.up_name}
- **BVID**: {meta.bvid}
- **视频链接**: <{resolved_url}>
- **文件时间**: {meta.formatted_time}

---

## tags

#{category} #{tag_source}

## 总结



## AI总结

> 本总结由 {ai_provider} 生成

{summary}

## 视频文稿

{transcript}
"""


def replace_ai_summary(content: str, summary: str, ai_provider: str) -> str:
    summary = adjust_heading_levels(summary)
    section = f"## AI总结\n\n> 本总结由 {ai_provider} 生成\n\n{summary}\n\n"
    pattern = re.compile(r"## AI总结\n\n.*?(?=## 视频文稿|$)", re.DOTALL)
    if pattern.search(content):
        return pattern.sub(section, content)
    marker = "## 视频文稿"
    if marker in content:
        return content.replace(marker, section + marker, 1)
    return content.rstrip() + "\n\n" + section


def render_or_update_summary(
    text_file: Path,
    markdown_root: Path,
    ai: "AIService",
    logger: logging.Logger,
    *,
    force: bool = False,
) -> tuple[Path, str] | None:
    meta = parse_transcript_filename(text_file)
    if not meta:
        logger.info("跳过未识别的转录文件名：%s", text_file.name)
        return None
    target = md_path_for(meta, markdown_root, text_file)
    existing_content = target.read_text(encoding="utf-8") if target.exists() else ""

    needs_work = force or not target.exists()
    if not needs_work and existing_content:
        if "## AI总结" not in existing_content or "Error" in existing_content or "发生错误" in existing_content:
            needs_work = True
    if not needs_work:
        return None

    transcript = text_file.read_text(encoding="utf-8")
    provider, summary = ai.summarize(transcript)
    if existing_content:
        new_content = replace_ai_summary(existing_content, summary, provider)
    else:
        new_content = build_markdown(meta, transcript, summary, provider)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new_content, encoding="utf-8")
    return target, provider


