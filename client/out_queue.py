#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import sys
import shutil
import time

from bootstrap import config, get_path, get_standard_logger
from git_utils import git_repo_transaction, set_logger as git_utils_set_logger

# 日志
logger = get_standard_logger(__file__)
git_utils_set_logger(logger)

QUEUE_DIR = get_path("queue_dir")
DST_DIR = get_path("save_text_dir")

def out_queue(force: bool = False):
    """
    将文件从 queue/from_stt 移动到本地 save_text_dir。
    """
    def action():
        src_dir = QUEUE_DIR / "from_stt"
        if not src_dir.exists():
            logger.info(f"源目录 {src_dir} 不存在。")
            return None
            
        count = 0
        # 复制非隐藏文件到 DST_DIR
        for file_path in src_dir.iterdir():
            if file_path.is_file() and not file_path.name.startswith('.'):
                try:
                    target_path = DST_DIR / file_path.name
                    if force and target_path.exists():
                        logger.info(f"强制覆盖: 正在删除现有文件 {target_path}")
                        target_path.unlink()

                    shutil.move(str(file_path), str(DST_DIR))
                    count += 1
                    logger.debug(f"已将文件 {file_path.name} 移动到 {DST_DIR}")
                except Exception as e:
                    logger.error(f"移动文件 {file_path.name} 到 {DST_DIR} 失败: {e}")
                    
        if count > 0:
            commit_msg = f"已将 {count} 个文件从 from_stt 移动到本地存储"
            logger.info(commit_msg)
            return commit_msg
        else:
            logger.info("from_stt 目录中没有需要移动的文件。")
            return None

    git_repo_transaction(QUEUE_DIR, action)

if __name__ == "__main__":
    out_queue()