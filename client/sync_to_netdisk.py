#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import shutil
import re
import argparse

import sys
SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))
from dp_bilibili_api import dp_bilibili
from dp_logging import setup_logger

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

def sync_to_netdisk(force=False):
    """
    将 markdown 目录下的文件根据文件名中的日期进行整理，
    并复制到用户的“文档/我的坚果云/markdown”目录下。

    源文件格式: markdown/YYYY-MM-DD/[timestamp][...].md
    目标文件格式: Documents/我的坚果云/markdown/YYYY-MM/DD/[...].md

    例如:
    源: markdown/2020-03-03/[2020-03-03_16-39-42][猫咪老师田七].md
    目标: Documents/.../markdown/2020-03/03/[猫咪老师田七].md
    """
    try:
        # 1. 定义源目录和目标根目录
        # 源目录为当前脚本所在位置的 'markdown' 子目录
        source_dir = get_dir_in_config("save_text_dir").parent / "markdown"
        # 目标目录会自动定位到当前用户的“文档”文件夹
        dest_root_dir = config["netdisk_dir"] / "markdown"

        if not source_dir.is_dir():
            logger.info(f"错误：源目录 '{source_dir.resolve()}' 不存在或不是一个文件夹。")
            return

        logger.info(f"源目录: {source_dir.resolve()}")
        logger.info(f"目标根目录: {dest_root_dir.resolve()}")
        logger.info("-" * 30)

        # 2. 遍历源目录中的所有子目录
        for source_subdir in source_dir.iterdir():
            if not source_subdir.is_dir():
                continue

            # 3. 检查目录名是否为 YYYY-MM-DD 格式
            date_str = source_subdir.name
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', date_str):
                year = date_str[:4]        # "YYYY"
                month = date_str[5:7]      # "MM"
                year_month = date_str[:7]  # "YYYY-MM"
                day = date_str[8:10]       # "DD"

                # 4. 遍历日期子目录中的所有 .md 文件
                for source_file in source_subdir.glob("*.md"):
                    filename = source_file.name

                    # 5. 移除文件名中可能存在的时间戳部分, e.g., "[2020-03-03_16-39-42]"
                    new_filename = re.sub(r'^\[.*?\]', '', filename)

                    # 6. 按年/月/日的目录也有可能
                    dest_file_path = dest_root_dir / year / month / day / new_filename

                    if dest_file_path.exists():
                        if not force:
                            logger.debug(f"跳过 (已存在,按年/月/日的目录): {dest_file_path}")
                            continue
                    else:
                        # 6. 构建新目标路径
                        dest_file_path = dest_root_dir / year_month / day / new_filename

                    # 7. 如果目标文件不存在，则创建目录并复制
                    if force or not dest_file_path.exists():
                        logger.info(f"复制: {source_file.relative_to(source_dir)}")
                        dest_file_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source_file, dest_file_path)
                        logger.info(f"  -> 至: {dest_file_path}")
                    else:
                        logger.debug(f"跳过 (已存在): {dest_file_path}")
            else:
                logger.info(f"跳过 (目录格式不符): {date_str}")

    except Exception as e:
        logger.info(f"处理过程中发生错误: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="同步Markdown文件到网盘")
    parser.add_argument("-f", "--force", action="store_true", help="强制覆盖已存在的文件")
    args = parser.parse_args()

    sync_to_netdisk(force=args.force)
    logger.info("处理完成。")
