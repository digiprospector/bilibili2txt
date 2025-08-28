#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import shutil
import time

import sys
SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))
from dp_logging import setup_logger
from git_utils import reset_repo, push_changes, set_logger as git_utils_set_logger

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
TEMP_DIR = get_dir_in_config("temp_dir")
QUEUE_DIR = get_dir_in_config("queue_dir")

def copy_mssing_to_queue():
    src_filename = TEMP_DIR / "missing_input"
    dst_filename = QUEUE_DIR / "to_stt" / "new_videos.txt"

    while True:
        try:
            reset_repo(QUEUE_DIR)
            
            shutil.copy(src_filename, dst_filename)
            commit_msg = f"新增文件{dst_filename.name}, 共 {sum(1 for _ in dst_filename.open('r', encoding='utf-8'))} 行"
            
            logger.info(f"已将文件 {src_filename} 复制到 {dst_filename}")
            logger.info(f"提交信息: {commit_msg}")
            
            if not push_changes(QUEUE_DIR, commit_msg):
                logger.error("提交失败, 等待10秒重试")
                time.sleep(10)            
                continue
            break
        except Exception as e:
            logger.error(f"发生错误: {e}")
            time.sleep(10)
            logger.info("10秒后重试...")

if __name__ == "__main__":
    copy_mssing_to_queue()
    logger.info("处理完成。")
