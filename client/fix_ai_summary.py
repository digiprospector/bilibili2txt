#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import shutil
import argparse
from pathlib import Path

from bootstrap import get_standard_logger, get_path, config, ROOT_DIR
from ai_utils import BatchTaskProcessor, is_ai_response_error
from md_utils import extract_metadata_from_filename, update_or_add_ai_summary, build_markdown_content

# 日志
logger = get_standard_logger(__file__)

# Debug 模式标志
debug_mode = False


def update_netdisk_summary(local_md_path: Path, timestamp_str: str, new_summary: str, ai_name: str = None):
    """同步更新内容到网盘，如果网盘文件已存在，则只更新AI总结部分"""
    try:
        netdisk_dir = config.get("netdisk_dir")
        if not netdisk_dir or not Path(netdisk_dir).exists():
            logger.warning(f"网盘目录不存在, 跳过网盘同步: {netdisk_dir}")
            return

        dest_root_dir = Path(netdisk_dir) / "markdown"

        date_part = timestamp_str.split('_', 1)[0]
        year = date_part[:4]
        month = date_part[5:7]
        year_month = date_part[:7]
        day = date_part[8:10]
        
        new_filename = re.sub(r'^\[.*?\]', '', local_md_path.name)
        
        # 两种可能的目录结构
        path1 = dest_root_dir / year / month / day / new_filename
        path2 = dest_root_dir / year_month / day / new_filename
        
        # 优先使用已存在的路径，否则默认使用 path2
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


def scan_files_to_fix(save_text_path: Path, markdown_root: Path):
    """扫描需要修复的文件，返回待处理任务列表"""
    tasks = []
    
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
            ai_pattern = re.compile(r'## AI总结\n\n(.*?)(?=\n\n## 视频文稿|$)', re.DOTALL)
            ai_match = ai_pattern.search(original_content)
            
            if not ai_match:
                logger.info(f"检测到缺失 AI总结: {md_file_name}")
                needs_fix = True
            elif is_ai_response_error(ai_match.group(1).strip()):
                logger.info(f"检测到无效 AI总结 (Error): {md_file_name}")
                needs_fix = True
        
        if needs_fix:
            # 获取文稿内容
            transcript_match = re.search(r'## 视频文稿\n\n(.*)', original_content, re.DOTALL)
            transcript = transcript_match.group(1).strip() if transcript_match else text_file.read_text(encoding='utf-8')
            
            tasks.append({
                "md_file_name": md_file_name,
                "local_md_path": local_md_path,
                "original_content": original_content,
                "transcript": transcript,
                "timestamp_str": meta.get("timestamp_str", ""),
            })
            
    return tasks


def fix_summaries():
    save_text_path = get_path("save_text_dir")
    markdown_root = save_text_path.parent / "markdown"
    
    logger.info(f"开始遍历文本目录: {save_text_path}")
    
    # 统计数据
    stats = {"processed": 0, "error": 0}

    def on_result(task_id, ai_name, summary, meta):
        nonlocal stats
        md_file_name = meta["md_file_name"]
        local_md_path = meta["local_md_path"]
        
        if ai_name == "Error":
            logger.error(f"[❌ 修复失败] {md_file_name} (by {ai_name}): {summary}")
            stats["error"] += 1
            return

        # 稍微调整格式
        summary = summary.replace("**"", " **"")
        
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

    # 扫描文件
    logger.info("正在扫描待修复文件...")
    try:
        tasks = scan_files_to_fix(save_text_path, markdown_root)
    except KeyboardInterrupt:
        logger.warning("收到中断信号，停止扫描...")
        return
    except Exception as e:
        logger.error(f"扫描过程发生错误: {e}")
        return
    
    if not tasks:
        logger.info("没有发现需要修复的文件。")
        return
    
    # Debug 模式限制任务数量
    if debug_mode:
        max_tasks = len(config.get("open_ai_list", []))
        if len(tasks) > max_tasks:
            logger.info(f"Debug模式: 限制任务数量为 {max_tasks}")
            tasks = tasks[:max_tasks]
    
    # 启动分布式处理器
    processor = BatchTaskProcessor(on_result_callback=on_result)
    
    for task in tasks:
        processor.add_task(
            task["md_file_name"], 
            task["transcript"], 
            extra_info=task
        )
    
    logger.info(f"已加入 {len(tasks)} 个修复任务。等待处理完成...")
    processor.wait_and_stop()

    logger.info("=" * 50)
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
