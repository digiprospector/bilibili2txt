#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import sys
import shutil
import time


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
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path

from config import config
QUEUE_DIR = get_dir_in_config("queue_dir")
DST_DIR = get_dir_in_config("save_text_dir")

def out_queue():
    while True:
        try:
            reset_repo(QUEUE_DIR)
            SRC_DIR = QUEUE_DIR / "from_stt"
            
            count = 0
            # 复制非隐藏文件到 DST_DIR
            for file in SRC_DIR.iterdir():
                if file.is_file() and not file.name.startswith('.'):
                    try:
                        shutil.move(file, DST_DIR)
                        count += 1
                        logger.info(f"已将文件 {file} 复制到 {DST_DIR}")
                    except Exception as e:
                        logger.error(f"复制文件 {file} 到 {DST_DIR} 失败: {e}")
                        
            commit_msg = f"已将{count}个文件复制到 {DST_DIR}"
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
    out_queue()