#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Markdown 与元数据处理工具模块 - 统一管理文稿到 Markdown 的转换逻辑
"""

import re
from pathlib import Path
from typing import Dict, Any, Optional

# 正则表达式用于匹配 [时间戳][UP主名][视频标题][BVID].text 的格式
FILENAME_PATTERN = re.compile(r'\[(.*?)\]\[(.*?)\]\[(.*?)\]\[(.*?)\]\.text')

def extract_metadata_from_filename(filename: str) -> Optional[Dict[str, Any]]:
    """从文件名解析元数据"""
    match = FILENAME_PATTERN.match(filename)
    if not match:
        return None
    
    timestamp_str, up_name, title, bvid = match.groups()
    video_link = f"https://www.bilibili.com/video/{bvid}"
    
    try:
        date_part, time_part = timestamp_str.split('_', 1)
        formatted_time = f"{date_part} {time_part.replace('-', ':')}"
    except ValueError:
        formatted_time = timestamp_str

    return {
        "filename": filename,
        "timestamp_str": timestamp_str,
        "up_name": up_name,
        "title": title,
        "bvid": bvid,
        "video_link": video_link,
        "formatted_time": formatted_time,
        "date_folder": timestamp_str.split('_', 1)[0]
    }

def build_markdown_content(meta: Dict[str, Any], transcript: str, summary: Optional[str] = None, ai_name: Optional[str] = None) -> str:
    """构建初始 Markdown 内容或全量生成"""
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

def update_or_add_ai_summary(md_content: str, new_summary: str, ai_name: Optional[str] = None) -> str:
    """在 Markdown 内容中更新或添加 AI 总结部分"""
    credit = f"> 本总结由 {ai_name} 生成\n\n" if ai_name else ""
    summary_text = f"{credit}{new_summary}"
    
    # 模式: ## AI总结 开头, 到 ## 视频文稿 结束(或文件尾)
    ai_pattern = re.compile(r'(## AI总结\n\n)(.*?)(?=\n\n## 视频文稿|$)', re.DOTALL)
    if ai_pattern.search(md_content):
        return ai_pattern.sub(rf'\1{summary_text}', md_content)
    else:
        # 如果没有找到, 尝试插在 ## 视频文稿 之前
        transcript_match = re.search(r'## 视频文稿', md_content)
        if transcript_match:
            return md_content[:transcript_match.start()] + f"## AI总结\n\n{summary_text}\n\n" + md_content[transcript_match.start():]
        else:
            # 否则附在最后
            return md_content.rstrip() + f"\n\n## AI总结\n\n{summary_text}\n"
