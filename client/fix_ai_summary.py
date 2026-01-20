#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import re
import shutil
from pathlib import Path

# 设置路径
SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))

from config import config
from openai_chat import analyze_stock_market
from dp_logging import setup_logger

# 日志
logger = setup_logger(Path(__file__).stem, log_dir=SCRIPT_DIR.parent / "logs")

# 正则表达式匹配文本文件名
# [timestamp][UP名][标题][BVID].text
FILENAME_PATTERN = re.compile(r'\[(.*?)\]\[(.*?)\]\[(.*?)\]\[(.*?)\]\.text')

def get_dir_in_config(key: str) -> Path:
    dir_path_str = config[key]
    if isinstance(dir_path_str, Path):
        dir_path = dir_path_str
    elif dir_path_str.startswith("/") or (len(dir_path_str) > 1 and dir_path_str[1] == ":"):
        dir_path = Path(dir_path_str)
    else:
        dir_path = SCRIPT_DIR.parent / dir_path_str
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path

def is_ai_summary_error(summary_text: str) -> bool:
    """检查AI总结是否包含错误关键词"""
    error_keywords = ["Error", "发生错误", "发生错误：", "API Key missing"]
    for kw in error_keywords:
        if kw in summary_text:
            return True
    return False

def update_or_add_ai_summary(md_content: str, new_summary: str) -> str:
    """在Markdown内容中更新或添加AI总结部分"""
    # 模式: ## AI总结 开头, 到 ## 视频文稿 结束(或文件尾)
    ai_pattern = re.compile(r'(## AI总结\n\n)(.*?)(?=\n\n## 视频文稿|$)', re.DOTALL)
    if ai_pattern.search(md_content):
        return ai_pattern.sub(rf'\1{new_summary}', md_content)
    else:
        # 如果没有找到, 尝试插在 ## 视频文稿 之前
        transcript_match = re.search(r'## 视频文稿', md_content)
        if transcript_match:
            return md_content[:transcript_match.start()] + f"## AI总结\n\n{new_summary}\n\n" + md_content[transcript_match.start():]
        else:
            # 否则附在最后
            return md_content.rstrip() + f"\n\n## AI总结\n\n{new_summary}\n"

def update_netdisk_summary(local_md_path: Path, timestamp_str: str, new_summary: str):
    """同步更新内容到网盘，如果网盘文件已存在，则只更新AI总结部分"""
    try:
        dest_root_dir = config["netdisk_dir"] / "markdown"
        if not dest_root_dir.parent.exists():
            logger.warning(f"网盘目录不存在, 跳过网盘同步: {config['netdisk_dir']}")
            return

        # 路径解析逻辑 (源自 sync_to_netdisk.py)
        date_part = timestamp_str.split('_', 1)[0]
        year = date_part[:4]
        month = date_part[5:7]
        year_month = date_part[:7]
        day = date_part[8:10]
        
        # 移除文件名中的时间戳
        new_filename = re.sub(r'^\[.*?\]', '', local_md_path.name)
        
        # 查找网盘中的文件位置 (支持两种目录结构)
        path1 = dest_root_dir / year / month / day / new_filename
        path2 = dest_root_dir / year_month / day / new_filename
        
        dest_file = None
        if path1.exists():
            dest_file = path1
        elif path2.exists():
            dest_file = path2
        else:
            # 如果都不存在, 默认使用其中一个路径
            dest_file = path2
            
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        
        if dest_file.exists():
            # 部分更新
            dest_content = dest_file.read_text(encoding='utf-8')
            updated_dest_content = update_or_add_ai_summary(dest_content, new_summary)
            dest_file.write_text(updated_dest_content, encoding='utf-8')
            logger.info(f"  -> 网盘部分项更新成功: {dest_file}")
        else:
            # 全量复制
            shutil.copy2(local_md_path, dest_file)
            logger.info(f"  -> 网盘文件创建成功: {dest_file}")
            
    except Exception as e:
        logger.error(f"  -> 网盘同步失败: {e}")

def fix_summaries():
    save_text_path = get_dir_in_config("save_text_dir")
    markdown_root = save_text_path.parent / "markdown"
    
    logger.info(f"开始遍历文本目录: {save_text_path}")
    
    for text_file in save_text_path.glob("*.text"):
        match = FILENAME_PATTERN.match(text_file.name)
        if not match:
            continue
            
        timestamp_str, up_name, title, bvid = match.groups()
        date_folder = timestamp_str.split('_', 1)[0]
        md_file_name = text_file.name.replace(".text", ".md")
        local_md_path = markdown_root / date_folder / md_file_name
        
        needs_fix = False
        original_content = ""
        
        if not local_md_path.exists():
            logger.info(f"检测到缺失 Markdown: {md_file_name}")
            needs_fix = True
            # 从 generate_md.py 复制的模板
            formatted_time = timestamp_str.replace('_', ' ').replace('-', ':', 2) # 简化转换
            video_link = f"https://www.bilibili.com/video/{bvid}"
            original_content = f"""# {title}

- **UP主**: {up_name}
- **BVID**: {bvid}
- **视频链接**: <{video_link}>
- **文件时间**: {formatted_time}

---

## tags



## 总结



## 视频文稿

{text_file.read_text(encoding='utf-8')}
"""
        else:
            original_content = local_md_path.read_text(encoding='utf-8')
            # 检查 AI总结
            ai_pattern = re.compile(r'## AI总结\n\n(.*?)(?=\n\n## 视频文稿|$)', re.DOTALL)
            ai_match = ai_pattern.search(original_content)
            
            if not ai_match:
                logger.info(f"检测到缺失 AI总结: {md_file_name}")
                needs_fix = True
            else:
                summary_text = ai_match.group(1).strip()
                if is_ai_summary_error(summary_text):
                    logger.info(f"检测到无效 AI总结 (Error): {md_file_name}")
                    needs_fix = True
        
        if needs_fix:
            logger.info(f"正在修复: {md_file_name} ...")
            transcript = text_file.read_text(encoding='utf-8')
            # 生成新总结
            new_summary = analyze_stock_market(transcript)
            new_summary = new_summary.replace("**“", " **“") # 格式优化
            
            new_content = update_or_add_ai_summary(original_content, new_summary)
            
            # 保存本地
            local_md_path.parent.mkdir(parents=True, exist_ok=True)
            local_md_path.write_text(new_content, encoding='utf-8')
            logger.info(f"  -> 本地修复完成: {local_md_path}")
            
            # 同步网盘 (只更新 AI 总结部分)
            update_netdisk_summary(local_md_path, timestamp_str, new_summary)

if __name__ == "__main__":
    fix_summaries()
    logger.info("修复任务执行完毕。")
