#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
将 markdown 目录下的文件根据文件名中的日期进行整理，
并复制到用户的网盘目录下。

源文件格式: markdown/YYYY-MM-DD/[timestamp][...].md
目标文件格式: netdisk_dir/markdown/YYYY/MM/DD/[...].md 或 YYYY-MM/DD/[...].md

例如:
源: markdown/2020-03-03/[2020-03-03_16-39-42][猫咪老师田七].md
目标: netdisk_dir/markdown/2020/03/03/[猫咪老师田七].md
"""

import argparse
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from bootstrap import config, get_standard_logger, SAVE_TEXT_DIR

logger = get_standard_logger(__file__)

# 日期目录正则: YYYY-MM-DD
DATE_DIR_PATTERN = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')
# 文件名时间戳前缀正则: [YYYY-MM-DD_HH-MM-SS]
TIMESTAMP_PREFIX_PATTERN = re.compile(r'^\[.*?\]')


@dataclass
class SyncStats:
    """同步统计信息"""
    copied: int = 0
    skipped_existing: int = 0
    skipped_invalid_dir: int = 0


def get_source_dir() -> Path:
    """获取源目录路径（markdown目录）"""
    return SAVE_TEXT_DIR.parent / "markdown"


def get_dest_root_dir() -> Path:
    """获取目标根目录路径"""
    netdisk_dir = config.get("netdisk_dir")
    if netdisk_dir is None:
        raise ValueError("配置中未找到 'netdisk_dir'")
    return Path(netdisk_dir) / "markdown"


def clean_filename(filename: str) -> str:
    """移除文件名中的时间戳前缀，例如 [2020-03-03_16-39-42]"""
    return TIMESTAMP_PREFIX_PATTERN.sub('', filename)


def find_dest_path(dest_root: Path, year: str, month: str, day: str, filename: str) -> tuple[Path, bool]:
    """
    查找目标文件路径，检查多种目录结构。
    
    Args:
        dest_root: 目标根目录
        year: 年份 (YYYY)
        month: 月份 (MM)
        day: 日期 (DD)
        filename: 清理后的文件名
        
    Returns:
        (目标路径, 是否已存在)
    """
    # 优先检查 YYYY/MM/DD 结构
    path_ymd = dest_root / year / month / day / filename
    if path_ymd.exists():
        return path_ymd, True
    
    # 其次检查 YYYY-MM/DD 结构
    path_ym_d = dest_root / f"{year}-{month}" / day / filename
    if path_ym_d.exists():
        return path_ym_d, True
    
    # 不存在时，使用 YYYY/MM/DD 结构
    return path_ymd, False


def process_markdown_file(source_file: Path, dest_root: Path, 
                          year: str, month: str, day: str, 
                          force: bool, stats: SyncStats) -> None:
    """处理单个 Markdown 文件"""
    new_filename = clean_filename(source_file.name)
    dest_path, exists = find_dest_path(dest_root, year, month, day, new_filename)
    
    if exists and not force:
        logger.debug(f"跳过 (已存在): {dest_path}")
        stats.skipped_existing += 1
        return
    
    # 复制文件
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, dest_path)
    logger.info(f"复制: {source_file.name} -> {dest_path}")
    stats.copied += 1


def process_date_directory(date_dir: Path, dest_root: Path, 
                           force: bool, stats: SyncStats) -> None:
    """处理日期目录"""
    match = DATE_DIR_PATTERN.match(date_dir.name)
    if not match:
        logger.debug(f"跳过 (目录格式不符): {date_dir.name}")
        stats.skipped_invalid_dir += 1
        return
    
    year, month, day = match.groups()
    
    for md_file in date_dir.glob("*.md"):
        process_markdown_file(md_file, dest_root, year, month, day, force, stats)


def sync_to_netdisk(force: bool = False) -> None:
    """
    将 markdown 目录下的文件根据文件名中的日期进行整理，
    并复制到用户的网盘目录下。
    
    Args:
        force: 是否强制覆盖已存在的文件
    """
    try:
        source_dir = get_source_dir()
        dest_root_dir = get_dest_root_dir()
        
        if not source_dir.is_dir():
            logger.error(f"源目录不存在或不是文件夹: {source_dir.resolve()}")
            return
        
        logger.info(f"源目录: {source_dir.resolve()}")
        logger.info(f"目标根目录: {dest_root_dir.resolve()}")
        logger.info("-" * 50)
        
        stats = SyncStats()
        
        # 遍历源目录中的所有子目录
        for subdir in sorted(source_dir.iterdir()):
            if subdir.is_dir():
                process_date_directory(subdir, dest_root_dir, force, stats)
        
        # 输出统计信息
        logger.info("-" * 50)
        logger.info(f"同步完成: 复制 {stats.copied} 个文件, "
                    f"跳过 {stats.skipped_existing} 个已存在文件, "
                    f"跳过 {stats.skipped_invalid_dir} 个无效目录")
        
    except Exception as e:
        logger.exception(f"处理过程中发生错误: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="同步Markdown文件到网盘",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s           # 同步新文件，跳过已存在的
  %(prog)s -f        # 强制覆盖所有文件
        """
    )
    parser.add_argument(
        "-f", "--force", 
        action="store_true", 
        help="强制覆盖已存在的文件"
    )
    args = parser.parse_args()
    
    sync_to_netdisk(force=args.force)


if __name__ == "__main__":
    main()
