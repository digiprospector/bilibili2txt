#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from bootstrap import get_path, get_standard_logger
from git_utils import push_changes, set_logger as git_utils_set_logger

# 日志
logger = get_standard_logger(__file__)
git_utils_set_logger(logger)

DATA_DIR = get_path("data_dir")

def push_data_repo():
    """推送 data 仓库的更改"""
    logger.info("正在推送 data 仓库...")
    if push_changes(DATA_DIR, "update"):
        logger.info("data 仓库推送成功。")
    else:
        logger.error("data 仓库推送失败。")
    
if __name__ == "__main__":
    push_data_repo()