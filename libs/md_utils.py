#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Markdown 与元数据处理工具模块 - 统一管理文稿到 Markdown 的转换逻辑

主要功能:
- 从文件名解析视频元数据
- 构建 Markdown 内容
- 更新/添加 AI 总结
"""

import re
from dataclasses import dataclass
from typing import Optional

# 正则表达式：匹配 [时间戳][UP主名][视频标题][BVID].text 格式
FILENAME_PATTERN = re.compile(r'\[(.*?)\]\[(.*?)\]\[(.*?)\]\[(.*?)\]\.text')

# AI 总结正则：从 ## AI总结 到 ## 视频文稿 或文件尾
AI_SUMMARY_PATTERN = re.compile(r'(## AI总结\n\n)(.*?)(?=\n\n## 视频文稿|$)', re.DOTALL)


@dataclass
class VideoMetadata:
    """视频元数据"""
    filename: str
    timestamp_str: str
    up_name: str
    title: str
    bvid: str
    video_link: str
    formatted_time: str
    date_folder: str
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "filename": self.filename,
            "timestamp_str": self.timestamp_str,
            "up_name": self.up_name,
            "title": self.title,
            "bvid": self.bvid,
            "video_link": self.video_link,
            "formatted_time": self.formatted_time,
            "date_folder": self.date_folder,
        }


def extract_metadata_from_filename(filename: str) -> Optional[dict]:
    """
    从文件名解析元数据
    
    Args:
        filename: 文件名，格式为 [时间戳][UP主名][视频标题][BVID].text
        
    Returns:
        元数据字典，解析失败返回 None
    """
    match = FILENAME_PATTERN.match(filename)
    if not match:
        return None
    
    timestamp_str, up_name, title, bvid = match.groups()
    
    # 格式化时间
    try:
        date_part, time_part = timestamp_str.split('_', 1)
        formatted_time = f"{date_part} {time_part.replace('-', ':')}"
    except ValueError:
        formatted_time = timestamp_str
        date_part = timestamp_str

    return VideoMetadata(
        filename=filename,
        timestamp_str=timestamp_str,
        up_name=up_name,
        title=title,
        bvid=bvid,
        video_link=f"https://www.bilibili.com/video/{bvid}",
        formatted_time=formatted_time,
        date_folder=date_part,
    ).to_dict()


def build_markdown_content(
    meta: dict, 
    transcript: str, 
    summary: Optional[str] = None, 
    ai_name: Optional[str] = None
) -> str:
    """
    构建 Markdown 内容
    
    Args:
        meta: 视频元数据字典
        transcript: 视频文稿内容
        summary: AI 总结（可选）
        ai_name: AI 名称（可选）
        
    Returns:
        完整的 Markdown 内容
    """
    summary_section = ""
    if summary:
        credit = f"> 本总结由 {ai_name} 生成\n\n" if ai_name else ""
        summary_section = f"## AI总结\n\n{credit}{summary}\n\n"

    return f"""# {meta['title']}

- **UP主**: {meta['up_name']}
- **BVID**: {meta['bvid']}
- **视频链接**: <{meta['video_link']}>
- **文件时间**: {meta['formatted_time']}

---

## tags



## 总结



{summary_section}## 视频文稿

{transcript}
"""


def update_or_add_ai_summary(
    md_content: str, 
    new_summary: str, 
    ai_name: Optional[str] = None
) -> str:
    """
    在 Markdown 内容中更新或添加 AI 总结部分
    
    Args:
        md_content: 原始 Markdown 内容
        new_summary: 新的 AI 总结
        ai_name: AI 名称（可选）
        
    Returns:
        更新后的 Markdown 内容
    """
    credit = f"> 本总结由 {ai_name} 生成\n\n" if ai_name else ""
    summary_text = f"{credit}{new_summary}"
    
    # 尝试替换现有的 AI 总结
    if AI_SUMMARY_PATTERN.search(md_content):
        return AI_SUMMARY_PATTERN.sub(rf'\1{summary_text}', md_content)
    
    # 如果没有找到，尝试插在 ## 视频文稿 之前
    transcript_match = re.search(r'## 视频文稿', md_content)
    if transcript_match:
        insert_pos = transcript_match.start()
        return (
            md_content[:insert_pos] + 
            f"## AI总结\n\n{summary_text}\n\n" + 
            md_content[insert_pos:]
        )
    
    # 否则附在最后
    return md_content.rstrip() + f"\n\n## AI总结\n\n{summary_text}\n"
