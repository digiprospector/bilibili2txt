#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import re
import shutil
import threading
import queue
import time
import signal
import argparse
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

# 设置路径
SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))

from config import config
from ai_utils import BatchTaskProcessor, is_ai_response_error
from md_utils import extract_metadata_from_filename, update_or_add_ai_summary, build_markdown_content
from dp_logging import setup_logger

# 日志
logger = setup_logger(Path(__file__).stem, log_dir=SCRIPT_DIR.parent / "logs")

# Debug 模式标志
debug_mode = False

def get_dir_in_config(key: str) -> Path:
    dir_path_str = config[key]
    if isinstance(dir_path_str, Path):
        dir_path = dir_path_str
    elif dir_path_str.startswith("/") or (len(dir_path_str) > 1 and dir_path_str[1] == ":"):
        dir_path = Path(dir_path_str)
    else:
        dir_path = SCRIPT_DIR.parent / dir_path_str
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path

def update_netdisk_summary(local_md_path: Path, timestamp_str: str, new_summary: str, ai_name: Optional[str] = None):
    """同步更新内容到网盘，如果网盘文件已存在，则只更新AI总结部分"""
    try:
        dest_root_dir = config["netdisk_dir"] / "markdown"
        if not dest_root_dir.parent.exists():
            logger.warning(f"网盘目录不存在, 跳过网盘同步: {config['netdisk_dir']}")
            return

        date_part = timestamp_str.split('_', 1)[0]
        year = date_part[:4]
        month = date_part[5:7]
        year_month = date_part[:7]
        day = date_part[8:10]
        
        new_filename = re.sub(r'^\[.*?\]', '', local_md_path.name)
        
        path1 = dest_root_dir / year / month / day / new_filename
        path2 = dest_root_dir / year_month / day / new_filename
        
        dest_file = None
        if path1.exists():
            dest_file = path1
        elif path2.exists():
            dest_file = path2
        else:
            dest_file = path2
            
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        
        if dest_file.exists():
            dest_content = dest_file.read_text(encoding='utf-8')
            updated_dest_content = update_or_add_ai_summary(dest_content, new_summary, ai_name)
            dest_file.write_text(updated_dest_content, encoding='utf-8')
            logger.info(f"  -> 网盘部分项更新成功: {dest_file}")
        else:
            shutil.copy2(local_md_path, dest_file)
            logger.info(f"  -> 网盘文件创建成功: {dest_file}")
            
    except Exception as e:
        logger.error(f"  -> 网盘同步失败: {e}")

def fix_summaries():
    save_text_path = get_dir_in_config("save_text_dir")
    markdown_root = save_text_path.parent / "markdown"
    
    logger.info(f"开始遍历文本目录: {save_text_path}")
    
    # 统计数据
    stats = {"processed": 0, "error": 0, "skipped": 0, "added": 0}

    def on_result(task_id, ai_name, summary, meta):
        nonlocal stats
        md_file_name = meta["md_file_name"]
        local_md_path = meta["local_md_path"]
        
        if ai_name == "Error":
            logger.error(f"[❌ 修复失败] {md_file_name} (by {ai_name}): {summary}")
            stats["error"] += 1
            return

        # 稍微调整格式
        summary = summary.replace("**“", " **“")
        
        # 更新内容
        new_content = update_or_add_ai_summary(meta["original_content"], summary, ai_name)
        
        try:
            local_md_path.parent.mkdir(parents=True, exist_ok=True)
            local_md_path.write_text(new_content, encoding='utf-8')
            logger.info(f"[✅ 修复完成] {md_file_name} (by {ai_name})")
            
            # 同步网盘
            update_netdisk_summary(local_md_path, meta["timestamp_str"], summary, ai_name)
            stats["processed"] += 1
        except Exception as e:
            logger.error(f"[❌ 写入失败] {md_file_name}: {e}")
            stats["error"] += 1

    # 启动分布式处理器
    processor = BatchTaskProcessor(on_result_callback=on_result)
    
    logger.info("正在扫描待修复文件...")
    
    try:
        for text_file in save_text_path.glob("*.text"):
            meta = extract_metadata_from_filename(text_file.name)
            if not meta:
                continue
                
            md_file_name = text_file.name.replace(".text", ".md")
            local_md_path = markdown_root / meta["date_folder"] / md_file_name
            
            needs_fix = False
            original_content = ""
            
            if not local_md_path.exists():
                logger.info(f"检测到缺失 Markdown，将全量创建: {md_file_name}")
                needs_fix = True
                transcript = text_file.read_text(encoding='utf-8')
                original_content = build_markdown_content(meta, transcript)
            else:
                original_content = local_md_path.read_text(encoding='utf-8')
                # 检查 AI总结
                ai_pattern = re.compile(r'## AI总结\n\n(.*?)(?=\n\n## 视频文稿|$)', re.DOTALL)
                ai_match = ai_pattern.search(original_content)
                
                if not ai_match:
                    logger.info(f"检测到缺失 AI总结: {md_file_name}")
                    needs_fix = True
                else:
                    summary_text = ai_match.group(1).strip()
                    if is_ai_response_error(summary_text):
                        logger.info(f"检测到无效 AI总结 (Error): {md_file_name}")
                        needs_fix = True
            
            if needs_fix:
                task_meta = {
                    **meta,
                    "md_file_name": md_file_name,
                    "local_md_path": local_md_path,
                    "original_content": original_content,
                }
                
                # 获取最新的原文稿
                # 如果是新文件，original_content 已经包含了文稿，但这里为了统一处理，我们再次提取
                transcript_match = re.search(r'## 视频文稿\n\n(.*)', original_content, re.DOTALL)
                transcript = transcript_match.group(1).strip() if transcript_match else text_file.read_text(encoding='utf-8')
                
                processor.add_task(md_file_name, transcript, extra_info=task_meta)
                stats["added"] += 1
                
                if debug_mode and stats["added"] >= len(config.get("open_ai_list", [])):
                    logger.info(f"Debug模式: 已入队 {stats['added']} 个任务，停止扫描")
                    break
                    
    except KeyboardInterrupt:
        logger.warning("收到中断信号，停止扫描...")
    except Exception as e:
        logger.error(f"扫描过程发生错误: {e}")

    if stats["added"] > 0:
        logger.info(f"已加入 {stats['added']} 个修复任务。等待处理完成...")
        processor.wait_and_stop()
    else:
        logger.info("没有发现需要修复的文件。")
        processor.wait_and_stop()

    logger.info(f"=" * 50)
    logger.info(f"修复任务结束: 成功 {stats['processed']}, 失败 {stats['error']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="修复缺失或无效的 AI 总结")
    parser.add_argument("--debug", action="store_true", help="Debug模式: 限制任务数量")
    args = parser.parse_args()
    
    if args.debug:
        debug_mode = True
        logger.info("Debug模式已启用")
    
    fix_summaries()
    logger.info("任务执行完毕。")
