#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from pathlib import Path
import shutil
import sys

SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))
from dp_logging import setup_logger
from git_utils import reset_repo, push_changes, set_logger as git_utils_set_logger

# 日志
logger = setup_logger(Path(__file__).stem, log_dir=SCRIPT_DIR.parent / "logs")
git_utils_set_logger(logger)

def set_logger(logger_instance):
    global logger
    logger = logger_instance
    git_utils_set_logger(logger_instance)

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
TEMP_DIR = get_dir_in_config("temp_dir")
SRC_DIR = TEMP_DIR / "server_text"
ID_FILE= SCRIPT_DIR / "id"

def in_queue():    
    while True:
        try:
            reset_repo(QUEUE_DIR)
            input_files = sorted([f for f in SRC_DIR.glob("*") if not f.name.startswith(".") and f.is_file()])
            if input_files:
                logger.info(f"复制 {len(input_files)} 个已处理的文件到 {QUEUE_DIR / 'from_stt'}")
                for input_file in input_files:
                    shutil.copy(input_file, QUEUE_DIR / "from_stt" / input_file.name)
                id = ""
                if ID_FILE.exists():
                    with ID_FILE.open('r', encoding='utf-8') as f_id:
                        id = f"{f_id.read().strip()}, "
                if not push_changes(QUEUE_DIR, f"{id}上传 {len(input_files)} 个已处理的文件"):
                    logger.error("提交失败, 等待10秒重试")
                    time.sleep(10) 
                    continue
                for input_file in input_files:
                    input_file.unlink()
            else:
                logger.info(f"{SRC_DIR} 目录中没有已处理的文件，退出")
                break
        except Exception as e:
            logger.error(f"发生错误: {e}")
            time.sleep(10)
            logger.info("10秒后重试...")

if __name__ == "__main__":
    in_queue()