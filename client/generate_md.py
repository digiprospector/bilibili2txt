#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import shutil
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import sys
SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))
from dp_bilibili_api import dp_bilibili
from dp_logging import setup_logger
from ai_utils import get_all_ai_configs, analyze_stock_market, get_all_ai_summaries, process_tasks_distributed, BatchTaskProcessor
from md_utils import extract_metadata_from_filename, build_markdown_content

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


def create_markdown_files_from_text(force: bool = False):
    """
    遍历指定目录，为每个 .text 文件创建一个对应的 .md 文件。
    采用流式生产者-消费者模式：边扫描边加入队列进行处理。
    """
    source_path = get_dir_in_config("save_text_dir")
    logger.info(f"\n--- 开始处理 '{source_path}' 目录下的文稿文件 (流式并行模式) ---")

    if not source_path.is_dir():
        logger.error(f"错误: 目录 '{source_path}' 不存在或不是一个有效的目录。")
        return

    filename_pattern = re.compile(r'\[(.*?)\]\[(.*?)\]\[(.*?)\]\[(.*?)\]\.text')
    
    text_files = list(source_path.glob("*.text"))
    if not text_files:
        logger.info("没有发现需要处理的 .text 文件。")
        return

    # 初始化统计数据
    processed_count = 0
    error_count = 0
    skipped_count = 0
    added_to_queue_count = 0

    # 定义处理结果的回调函数
    def on_ai_result(task_id, ai_name, summary, meta):
        nonlocal processed_count, error_count
        md_filepath = meta["md_filepath"]
        
        if ai_name == "Error":
            logger.error(f"  - [失败] {meta['filename']}: {summary}")
            error_count += 1
            return

        md_content = build_markdown_content(meta, meta["transcript"], summary, ai_name)
        try:
            md_filepath.parent.mkdir(parents=True, exist_ok=True)
            md_filepath.write_text(md_content, encoding='utf-8')
            logger.info(f"  - [成功] (AI: {ai_name}) 已创建 Markdown: '{md_filepath.name}'")
            processed_count += 1
        except Exception as e:
            logger.error(f"  - [写入失败] {meta['filename']}: {e}")
            error_count += 1

    # 启动任务处理器
    processor = BatchTaskProcessor(on_result_callback=on_ai_result)

    logger.info("正在扫描文件并加入任务队列...")

    for text_filepath in text_files:
        meta = extract_metadata_from_filename(text_filepath.name)
        if not meta:
            logger.debug(f"  - [跳过] 文件名格式不匹配: {text_filepath.name}")
            continue
            
        meta["text_filepath"] = text_filepath
        target_dir = text_filepath.parent.parent / "markdown" / meta["date_folder"]
        md_filepath = (target_dir / text_filepath.name).with_suffix('.md')
        
        if not force and md_filepath.exists():
            skipped_count += 1
            continue
            
        try:
            transcript = text_filepath.read_text(encoding='utf-8')
            meta["transcript"] = transcript
            meta["md_filepath"] = md_filepath
            # 加入队列，立即开始处理
            processor.add_task(text_filepath.name, transcript, extra_info=meta)
            added_to_queue_count += 1
        except Exception as e:
            logger.error(f"读取或添加文件 {text_filepath.name} 失败: {e}")

    if added_to_queue_count == 0:
        logger.info(f"没有发现需要处理的新文件。跳过了 {skipped_count} 个已存在的文件。")
        # 记得也要停止处理器，虽然没给它发任务
        processor.wait_and_stop()
    else:
        logger.info(f"已将 {added_to_queue_count} 个任务加入队列。等待处理完成...")
        processor.wait_and_stop()
    
    logger.info(f"\n处理完成: 成功 {processed_count}, 失败 {error_count}, 跳过 {skipped_count}.")

if __name__ == "__main__":
    create_markdown_files_from_text()