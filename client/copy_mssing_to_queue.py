#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import shutil
from pathlib import Path

from bootstrap import get_standard_logger, QUEUE_DIR, TEMP_DIR
from git_utils import git_repo_transaction, set_logger as git_utils_set_logger

# 日志
logger = get_standard_logger(__file__)
git_utils_set_logger(logger)


def copy_missing_to_queue():
    src_filename = TEMP_DIR / "missing_input"
    dst_filename = QUEUE_DIR / "to_stt" / "new_videos.txt"

    def action():
        shutil.copy(src_filename, dst_filename)
        line_count = sum(1 for _ in dst_filename.open('r', encoding='utf-8'))
        commit_msg = f"新增文件 {dst_filename.name}, 共 {line_count} 行"
        logger.info(f"已将文件 {src_filename} 复制到 {dst_filename}")
        return commit_msg

    def on_success(commit_msg):
        logger.info(f"成功推送: {commit_msg}")

    git_repo_transaction(QUEUE_DIR, action, on_success)


if __name__ == "__main__":
    copy_missing_to_queue()
    logger.info("处理完成。")
