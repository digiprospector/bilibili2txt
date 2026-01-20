#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import shutil
import re

import sys
SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))
from dp_bilibili_api import dp_bilibili
from dp_logging import setup_logger
from openai_chat import analyze_stock_market

# 日志
logger = setup_logger(Path(__file__).stem, log_dir=SCRIPT_DIR.parent / "logs")

# 读取配置文件
CONFIG_FILE = SCRIPT_DIR.parent / "common/config.py"
CONFIG_SAMPLE_FILE = SCRIPT_DIR.parent / "common/config_sample.py"

def create_config_file():
    if not CONFIG_FILE.exists():
        logger.info(f"未找到配置文件 {CONFIG_FILE}，将从 {CONFIG_SAMPLE_FILE} 复制。")
        try:
            
            shutil.copy(CONFIG_SAMPLE_FILE, CONFIG_FILE)
        except Exception as e:
            logger.error(f"从 {CONFIG_SAMPLE_FILE} 复制配置文件失败: {e}")
            exit()
create_config_file()

def get_dir_in_config(key: str) -> Path:
    dir_path_str = config[key]
    if dir_path_str.startswith("/"):
        dir_path = Path(dir_path_str)
    else:
        dir_path = SCRIPT_DIR.parent / dir_path_str
    logger.debug(f"config[{key}] 的路径: {dir_path}")
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path

from config import config

def process_single_file(text_filepath, filename_pattern, force):
    filename = text_filepath.name
    match = filename_pattern.match(filename)
    if not match:
        logger.info(f"  - [跳过] 文件名格式不匹配: {filename}")
        return "ignored"

    try:
        logger.debug(f"开始处理文件{filename}")

        # 从匹配结果中提取信息
        timestamp_str, up_name, title, bvid = match.groups()
        video_link = f"https://www.bilibili.com/video/{bvid}"

        # 将文件名中的时间戳转换为标准格式
        # 原始格式: 2023-04-01_01-38-05
        # 目标格式: 2023-04-01 01:38:05
        try:
            date_part, time_part = timestamp_str.split('_', 1)
            formatted_time = f"{date_part} {time_part.replace('-', ':')}"
        except ValueError:
            formatted_time = timestamp_str # 格式不符则保留原样

        # 生成目录
        target_dir = text_filepath.parent.parent / "markdown" / f"{formatted_time[0:10]}"
        target_dir.mkdir(parents=True, exist_ok=True)

        # 使用与 .text 文件相同的文件名（仅替换后缀）来创建 .md 文件
        md_filepath = (target_dir / text_filepath.name).with_suffix('.md')

        # 使用 pathlib.Path.exists() 判断 markdown 文件是否存在，如果存在就跳过
        if not force and md_filepath.exists():
            logger.debug(f"  - [跳过] Markdown 文件已存在: '{md_filepath.name}'")
            return "skipped"

        # 使用 pathlib 的便捷方法读取文本
        transcript = text_filepath.read_text(encoding='utf-8')

        # AI总结
        ai_markdown = analyze_stock_market(f"{transcript}")
        ai_markdown = ai_markdown.replace("**“", " **“")

        # 构建 Markdown 内容
        md_content = f"""# {title}

- **UP主**: {up_name}
- **BVID**: {bvid}
- **视频链接**: <{video_link}>
- **文件时间**: {formatted_time}

---

## tags



## 总结



## AI总结

{ai_markdown}

## 视频文稿

{transcript}
"""
        # 使用 pathlib 的便捷方法写入文本
        md_filepath.write_text(md_content, encoding='utf-8')
        
        logger.info(f"  - [成功] 已为 '{filename}' 创建 Markdown 文件: '{md_filepath.name}'")
        return "processed"

    except Exception as e:
        logger.info(f"  - [失败] 处理文件 '{filename}' 时出错: {e}")
        return "error"

def create_markdown_files_from_text(force: bool = False):
    """
    遍历指定目录，为每个 .text 文件创建一个对应的 .md 文件。
    如果 .md 文件已存在，则跳过。
    
    文件名格式应为: `[时间戳][UP主名][视频标题][BVID].text`
    例如: `[2023-04-01_01-38-05][小木吱吱][为什么离开大厂去创业][BV1WT411s7z5].text`

    生成的 .md 文件将与对应的 .text 文件同名，仅后缀不同。

    Args:
        source_dir (str): 包含 .text 文件的源目录。
    """
    source_path = get_dir_in_config("save_text_dir")
    logger.info(f"\n--- 开始处理 '{source_path}' 目录下的文稿文件 ---")

    if not source_path.is_dir():
        logger.error(f"错误: 目录 '{source_path}' 不存在或不是一个有效的目录。")
        return

    # 正则表达式用于匹配 [内容1][内容2][内容3][内容4].text 的格式
    # 它会捕获每个方括号内的内容
    filename_pattern = re.compile(r'\[(.*?)\]\[(.*?)\]\[(.*?)\]\[(.*?)\]\.text')

    processed_count = 0
    skipped_count = 0
    
    # 使用 顺序处理
    for text_filepath in source_path.glob("*.text"):
        result = process_single_file(text_filepath, filename_pattern, force)
        if result == "processed":
            processed_count += 1
        elif result == "skipped":
            skipped_count += 1
    
    logger.info(f"\n处理完成，共创建了 {processed_count} 个 Markdown 文件，跳过了 {skipped_count} 个已存在的文件。")

if __name__ == "__main__":
    create_markdown_files_from_text()