#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from pathlib import Path
import sys
import shutil
import argparse

SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))
from dp_logging import setup_logger
from git_utils import reset_repo, push_changes, set_logger as git_utils_set_logger

# 日志
logger = setup_logger(Path(__file__).stem, log_dir=SCRIPT_DIR.parent / "logs")
git_utils_set_logger(logger)

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
    return dir_path

from config import config
QUEUE_DIR = get_dir_in_config("queue_dir")
NEW_VIDEO_LIST_DIR = get_dir_in_config("new_video_list_dir")
SAVE_NEW_VIDEO_LIST_DIR = get_dir_in_config("save_new_video_list_dir")

def in_queue():
    parser = argparse.ArgumentParser(
        description="将一个包含B站视频信息的txt文件复制到queue的to_stt目录中。然后提交queue仓库",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "input_file", nargs='?',
        help="包含B站视频链接的txt文件路径 (可选，如果未指定，则使用目录中的最后一个文件)."
    )
    
    target_dir = QUEUE_DIR / "to_stt"

    # 如果没有提供输入文件，使用当前目录中的最后一个文件
    args = parser.parse_args()
    if args.input_file:
        input_path = Path(args.input_file)
    else:
        # 获取当前目录中的所有文件
        files = sorted(NEW_VIDEO_LIST_DIR.glob("*"))
        input_path = files[-1] if files else None
    
    while True:
        try:
            reset_repo(QUEUE_DIR)
            
            shutil.copy(input_path, target_dir)
            commit_msg = f"新增文件{input_path.name}, 共 {sum(1 for _ in input_path.open('r', encoding='utf-8'))} 行"
            
            logger.info(f"已将文件 {input_path} 复制到 {target_dir}")
            logger.info(f"提交信息: {commit_msg}")
            
            if not push_changes(QUEUE_DIR, commit_msg):
                logger.error("提交失败, 等待10秒重试")
                time.sleep(10)
                continue
            shutil.move(input_path, SAVE_NEW_VIDEO_LIST_DIR / input_path.name)
            logger.info(f"已将文件移动到 {SAVE_NEW_VIDEO_LIST_DIR / input_path.name}")
            break
        except Exception as e:
            logger.error(f"发生错误: {e}")
            time.sleep(10)
            logger.info("10秒后重试...")

if __name__ == "__main__":
    in_queue()