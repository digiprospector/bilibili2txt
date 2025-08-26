#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from pathlib import Path
import shutil

from dp_logging import setup_logger
from git_utils import reset_repo, push_changes, set_logger as git_utils_set_logger

logger = setup_logger(Path(__file__).stem)
git_utils_set_logger(logger)

def set_logger(logger_instance):
    global logger
    logger = logger_instance

# --- Configuration ---
# Get the directory where the script is located
SCRIPT_DIR = Path(__file__).parent.resolve()

# Define directories relative to the script's location
ID_FILE= SCRIPT_DIR / "id"

def get_config():
    """Get the queue directory from the config file."""
    config_file = SCRIPT_DIR / "config.json"
    if not config_file.exists():
        logger.error(f"配置文件 {config_file} 不存在。")
        shutil.copy(SCRIPT_DIR / "config_sample.json", config_file)
        logger.info(f"已将 config_sample.json 复制到 {config_file}")

    import json
    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)

    return config
config = get_config()

def get_output_directory(config):
    output_path = Path(config.get("output_directory", "output"))

    if output_path.is_absolute():
        # 如果是绝对路径，直接使用
        return output_path
    else:
        # 如果是相对路径，则解析为相对于脚本目录的绝对路径
        return (SCRIPT_DIR / output_path).resolve()
OUTPUT_DIR = get_output_directory(config)

def get_queue_directory(config):
    queue_path = Path(config.get("queue_directory", "queue"))

    if queue_path.is_absolute():
        # 如果是绝对路径，直接使用
        return queue_path
    else:
        # 如果是相对路径，则解析为相对于脚本目录的绝对路径
        return (SCRIPT_DIR / queue_path).resolve()

def in_queue():
    queue_dir = get_queue_directory(config)
    
    while True:
        try:
            reset_repo(queue_dir)
            input_files = sorted([f for f in OUTPUT_DIR.glob("*") if not f.name.startswith(".") and f.is_file()])
            if input_files:
                logger.info(f"复制 {len(input_files)} 个已处理的文件到 {queue_dir / 'from_stt'}")
                for input_file in input_files:
                    shutil.copy(input_file, queue_dir / "from_stt" / input_file.name)
                id = ""
                if ID_FILE.exists():
                    with ID_FILE.open('r', encoding='utf-8') as f_id:
                        id = f"{f_id.read().strip()}, "
                push_changes(queue_dir, f"{id}上传 {len(input_files)} 个已处理的文件")
                for input_file in input_files:
                    input_file.unlink()
            else:
                logger.info(f"{OUTPUT_DIR} 目录中没有已处理的文件，退出")
                break
        except Exception as e:
            logger.error(f"发生错误: {e}")
            time.sleep(10)
            logger.info("10秒后重试...")

if __name__ == "__main__":
    in_queue()