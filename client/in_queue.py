#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from pathlib import Path
import sys
import shutil
import argparse

from bootstrap import get_path, get_standard_logger

# Import git utils (libs added by bootstrap)
from git_utils import reset_repo, push_changes, set_logger as git_utils_set_logger

# 日志
logger = get_standard_logger(__file__)
git_utils_set_logger(logger)

QUEUE_DIR = get_path("queue_dir")
NEW_VIDEO_LIST_DIR = get_path("new_video_list_dir")
SAVE_NEW_VIDEO_LIST_DIR = get_path("save_new_video_list_dir")


def get_input_file(args_input_file):
    """确定输入文件路径"""
    if args_input_file:
        return Path(args_input_file)
    
    # 获取目录中最新的 .txt 文件
    files = sorted(NEW_VIDEO_LIST_DIR.glob("*.txt"))
    return files[-1] if files else None

def process_file(input_path, target_dir):
    """执行单个文件的同步和移动"""
    while True:
        try:
            reset_repo(QUEUE_DIR)
            
            # 计算行数并复制
            line_count = sum(1 for _ in input_path.open('r', encoding='utf-8'))
            shutil.copy(input_path, target_dir)
            
            commit_msg = f"新增文件 {input_path.name}, 共 {line_count} 行"
            logger.info(f"已将文件 {input_path.name} 复制到 {target_dir}")
            
            if push_changes(QUEUE_DIR, commit_msg):
                # 移动到备份目录
                shutil.move(input_path, SAVE_NEW_VIDEO_LIST_DIR / input_path.name)
                logger.info(f"成功推送并将文件移动到 {SAVE_NEW_VIDEO_LIST_DIR}")
                return True
            else:
                logger.error("提交失败, 10秒后重试...")
                time.sleep(10)
        except Exception as e:
            logger.error(f"处理文件 {input_path.name} 时发生错误: {e}")
            time.sleep(10)
            logger.info("10秒后重试...")

def in_queue(input_path: Path):
    target_dir = QUEUE_DIR / "to_stt"
    process_file(input_path, target_dir)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="将B站视频 information 文件同步到 queue 仓库。",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "-i", "--input", dest="input_file",
        help="包含视频信息的 txt 文件路径 (可选，默认为目录中最新的文件)."
    )
    args = parser.parse_args()
    
    input_path = get_input_file(args.input_file)
    if not input_path:
        logger.info(f"没有指定输入文件，且在 {NEW_VIDEO_LIST_DIR} 中未找到可用文件。")
    else:
        in_queue(input_path)