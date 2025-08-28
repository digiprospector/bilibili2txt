#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from pathlib import Path
import sys
import shutil
import json

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
ID_FILE= SCRIPT_DIR / "id"

def out_queue(duration_limit=864000, limit_type="less_than"):
    if limit_type not in ["less_than", "better_greater_than"]:
        logger.error(f"未知的 limit_type: {limit_type}，应为 'less_than' 或 'better_greater_than'")
        return False
    
    bv_list_file = TEMP_DIR / "bv_list.txt"
    
    src_dir = QUEUE_DIR / "to_stt"
    
    while True:
        try:
            reset_repo(QUEUE_DIR)
            input_files = sorted([f for f in src_dir.glob("*") if not f.name.startswith(".") and f.is_file()])
            if not input_files:
                logger.info(f"{src_dir} 目录中没有待处理的文件，退出")
                break
            found = False
            second_found = False
            if limit_type == "less_than":
                select_line = ""
                select_line_index = 0
                select_file = ""
                # 逐个检查文件中的每一行，寻找时长小于 duration_limit 的任务
                for input_file in input_files:
                    with open(input_file, 'r', encoding='utf-8') as file:
                        lines = file.readlines()
                    for line_index, line in enumerate(lines):
                        line = line.strip()
                        try:
                            bv_info = json.loads(line)
                        except json.decoder.JSONDecodeError:
                            #不是json格式,直接通过
                            select_line = line
                            select_line_index = line_index
                            select_file = input_file
                            found = True
                            break
                        if bv_info["duration"] < duration_limit:
                            select_line = line
                            select_line_index = line_index
                            select_file = input_file
                            found = True
                            break
                    if found:
                        break
            elif limit_type == "better_greater_than":
                select_line = ""
                select_line_index = 0
                select_file = ""
                second_select_line = ""
                second_select_line_index = 0
                second_select_file = ""
                # 逐个检查文件中的每一行，寻找时长大于 duration_limit 的任务
                for input_file in input_files:
                    with open(input_file, 'r', encoding='utf-8') as file:
                        lines = file.readlines()
                    for line_index, line in enumerate(lines):
                        line = line.strip()
                        try:
                            bv_info = json.loads(line)
                        except json.decoder.JSONDecodeError:
                            #不是json格式,直接通过
                            select_line = line
                            select_line_index = line_index
                            select_file = input_file
                            found = True
                            break
                        if bv_info["duration"] > duration_limit:
                            select_line = line
                            select_line_index = line_index
                            select_file = input_file
                            found = True
                            break
                        elif not second_select_line:
                            second_select_line = line
                            second_select_line_index = line_index
                            second_select_file = input_file
                    if found:
                        break
                
                if not found:
                    logger.info(f"没有找到时长大于 {duration_limit} 秒的视频, 找其他的视频")
                    select_line = second_select_line
                    select_line_index = second_select_line_index
                    select_file = second_select_file
                    second_found = True
                    found = True
            else:
                logger.error(f"未知的 limit_type: {limit_type}")
                break
                                
            # 找到了符合条件的行
            if found:
                if limit_type == "less_than":
                    logger.info(f"找到时长小于 {duration_limit} 秒的任务: {select_line}，从 {select_file.name} 中移除该行")
                elif limit_type == "better_greater_than":
                    if second_found:
                        logger.info(f"没有找到时长大于 {duration_limit} 秒的任务, 选择时长小于 {duration_limit} 秒的任务: {select_line}，从 {select_file.name} 中移除该行")
                    else:
                        logger.info(f"找到时长大于 {duration_limit} 秒的任务: {select_line}，从 {select_file.name} 中移除该行")
                with select_file.open('r', encoding='utf-8') as f:
                    lines = f.readlines()
                remaining_lines = lines[:select_line_index] + lines[select_line_index + 1:]
                if not remaining_lines:
                    logger.info(f"文件 {select_file.name} 是空文件，已删除")
                    select_file.unlink()
                else:
                    with select_file.open('w', encoding='utf-8') as f_in:
                        f_in.writelines(remaining_lines)
                with bv_list_file.open('w', encoding='utf-8') as f_dst:
                    logger.info(f"写入 {select_line} 到 {bv_list_file.name}")
                    f_dst.write(select_line + "\n")
                commit_msg = f"处理 {select_file.name} 里的 {select_line}"
            else:
                logger.info(f"没有找到时长小于 {duration_limit} 秒的任务，退出")
                break
            
            id = ""
            if ID_FILE.exists():
                with ID_FILE.open('r', encoding='utf-8') as f_id:
                    id = f"{f_id.read().strip()}, "
            commit_msg = f"{id}处理 {select_file.name} 里的 {select_line}"
            
            if not push_changes(QUEUE_DIR, commit_msg):
                logger.error("提交失败, 等待10秒重试")
                time.sleep(10)
                continue
            return found
        except Exception as e:
            logger.error(f"发生错误: {e}")
            time.sleep(10)
            logger.info("10秒后重试...")

if __name__ == "__main__":
    if out_queue():
        exit(0)
    else:
        exit(1)