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
from ai_utils import analyze_stock_market, is_ai_response_error
from dp_logging import setup_logger

# 日志
logger = setup_logger(Path(__file__).stem, log_dir=SCRIPT_DIR.parent / "logs")

# 正则表达式匹配文本文件名
# [timestamp][UP名][标题][BVID].text
FILENAME_PATTERN = re.compile(r'\[(.*?)\]\[(.*?)\]\[(.*?)\]\[(.*?)\]\.text')

# 线程安全的锁 - 用于文件写入
file_lock = threading.Lock()

# 停止事件 - 用于优雅退出
stop_event = threading.Event()

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

def is_ai_summary_error(summary_text: str) -> bool:
    """检查AI总结是否包含错误关键词"""
    return is_ai_response_error(summary_text)

def update_or_add_ai_summary(md_content: str, new_summary: str) -> str:
    """在Markdown内容中更新或添加AI总结部分"""
    # 模式: ## AI总结 开头, 到 ## 视频文稿 结束(或文件尾)
    ai_pattern = re.compile(r'(## AI总结\n\n)(.*?)(?=\n\n## 视频文稿|$)', re.DOTALL)
    if ai_pattern.search(md_content):
        return ai_pattern.sub(rf'\1{new_summary}', md_content)
    else:
        # 如果没有找到, 尝试插在 ## 视频文稿 之前
        transcript_match = re.search(r'## 视频文稿', md_content)
        if transcript_match:
            return md_content[:transcript_match.start()] + f"## AI总结\n\n{new_summary}\n\n" + md_content[transcript_match.start():]
        else:
            # 否则附在最后
            return md_content.rstrip() + f"\n\n## AI总结\n\n{new_summary}\n"

def update_netdisk_summary(local_md_path: Path, timestamp_str: str, new_summary: str):
    """同步更新内容到网盘，如果网盘文件已存在，则只更新AI总结部分"""
    try:
        dest_root_dir = config["netdisk_dir"] / "markdown"
        if not dest_root_dir.parent.exists():
            logger.warning(f"网盘目录不存在, 跳过网盘同步: {config['netdisk_dir']}")
            return

        # 路径解析逻辑 (源自 sync_to_netdisk.py)
        date_part = timestamp_str.split('_', 1)[0]
        year = date_part[:4]
        month = date_part[5:7]
        year_month = date_part[:7]
        day = date_part[8:10]
        
        # 移除文件名中的时间戳
        new_filename = re.sub(r'^\[.*?\]', '', local_md_path.name)
        
        # 查找网盘中的文件位置 (支持两种目录结构)
        path1 = dest_root_dir / year / month / day / new_filename
        path2 = dest_root_dir / year_month / day / new_filename
        
        dest_file = None
        if path1.exists():
            dest_file = path1
        elif path2.exists():
            dest_file = path2
        else:
            # 如果都不存在, 默认使用其中一个路径
            dest_file = path2
            
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        
        if dest_file.exists():
            # 部分更新
            dest_content = dest_file.read_text(encoding='utf-8')
            updated_dest_content = update_or_add_ai_summary(dest_content, new_summary)
            dest_file.write_text(updated_dest_content, encoding='utf-8')
            logger.info(f"  -> 网盘部分项更新成功: {dest_file}")
        else:
            # 全量复制
            shutil.copy2(local_md_path, dest_file)
            logger.info(f"  -> 网盘文件创建成功: {dest_file}")
            
    except Exception as e:
        logger.error(f"  -> 网盘同步失败: {e}")


def analyze_with_ai_config(transcript: str, ai_config: Dict[str, Any]) -> str:
    """使用指定的 AI 配置分析文本"""
    return analyze_stock_market(transcript, ai_config)


def process_single_file(task: Dict[str, Any], ai_config: Dict[str, Any], failed_queue: queue.Queue) -> bool:
    """
    处理单个文件
    :param task: 包含文件信息的字典
    :param ai_config: AI 配置
    :param failed_queue: 失败任务队列
    :return: 是否成功
    """
    ai_name = ai_config.get("openai_api_name", "unknown")
    text_file = task["text_file"]
    md_file_name = task["md_file_name"]
    local_md_path = task["local_md_path"]
    original_content = task["original_content"]
    timestamp_str = task["timestamp_str"]
    
    try:
        logger.info(f"[{ai_name}] 正在修复: {md_file_name} ...")
        transcript = text_file.read_text(encoding='utf-8')
        
        # 使用指定 AI 配置生成新总结
        new_summary = analyze_with_ai_config(transcript, ai_config)
        
        # 检查是否返回错误
        if is_ai_summary_error(new_summary):
            logger.error(f"[{ai_name}] 修复失败 (AI返回错误): {md_file_name}")
            failed_queue.put(task)
            return False
        
        new_summary = new_summary.replace("**“", " **“")
        new_content = update_or_add_ai_summary(original_content, new_summary)
        
        # 使用锁保护文件写入
        with file_lock:
            local_md_path.parent.mkdir(parents=True, exist_ok=True)
            local_md_path.write_text(new_content, encoding='utf-8')
            logger.info(f"[{ai_name}]   -> 本地修复完成: {local_md_path}")
            
            # 同步网盘 (只更新 AI 总结部分)
            update_netdisk_summary(local_md_path, timestamp_str, new_summary)
        
        return True
        
    except Exception as e:
        logger.error(f"[{ai_name}] 修复失败 (异常): {md_file_name} - {e}")
        failed_queue.put(task)
        return False


# 生产者完成标志
producer_done = threading.Event()


def worker_thread(ai_config: Dict[str, Any], task_queue: queue.Queue, failed_queue: queue.Queue, results: Dict[str, int]):
    """
    工作线程 - 从共享队列获取任务
    """
    ai_name = ai_config.get("openai_api_name", "unknown")
    interval = float(ai_config.get("interval", 0))
    success_count = 0
    fail_count = 0
    
    logger.info(f"[{ai_name}] 工作线程启动, 间隔: {interval}秒")
    
    while not stop_event.is_set():
        try:
            # 非阻塞获取任务
            task = task_queue.get(timeout=1)
        except queue.Empty:
            # 队列空了，检查生产者是否已完成
            if producer_done.is_set() and task_queue.empty():
                break
            continue
        
        # 检查是否需要停止
        if stop_event.is_set():
            task_queue.put(task)  # 放回任务
            break
        
        # 处理任务
        success = process_single_file(task, ai_config, failed_queue)
        if success:
            success_count += 1
        else:
            fail_count += 1
        
        task_queue.task_done()
        
        # Debug 模式: 每个 AI 只处理一个任务
        if debug_mode:
            logger.info(f"[{ai_name}] Debug模式: 已处理一个任务, 退出")
            break
        
        # 遵守每个 AI 站点的请求间隔 (使用可中断的等待)
        if interval > 0 and not stop_event.is_set():
            stop_event.wait(timeout=interval)
    
    # 保存结果
    results[ai_name] = {"success": success_count, "fail": fail_count}
    logger.info(f"[{ai_name}] 工作线程结束, 成功: {success_count}, 失败: {fail_count}")


def fix_summaries():
    global producer_done
    producer_done.clear()  # 重置生产者完成标志
    
    save_text_path = get_dir_in_config("save_text_dir")
    markdown_root = save_text_path.parent / "markdown"
    
    logger.info(f"开始遍历文本目录: {save_text_path}")
    
    # 获取所有 AI 配置
    ai_list = config.get("open_ai_list", [])
    if not ai_list:
        logger.error("open_ai_list 为空，无法进行修复")
        return
    
    logger.info(f"使用 {len(ai_list)} 个 AI 站点并行处理")
    
    # 共享任务队列 - 所有 AI 从同一个队列获取任务
    # 队列长度限制为 AI 数量，这样生产者会等待消费者处理
    queue_size = len(ai_list)
    task_queue: queue.Queue = queue.Queue(maxsize=queue_size)
    logger.info(f"任务队列大小限制: {queue_size}")
    
    # 失败任务队列
    failed_queue: queue.Queue = queue.Queue()
    
    # 结果统计
    results: Dict[str, Dict[str, int]] = {}
    
    # 先启动所有工作线程 (设置为 daemon 线程以便主程序退出时自动终止)
    threads: List[threading.Thread] = []
    for ai_config in ai_list:
        ai_name = ai_config.get("openai_api_name", "unknown")
        t = threading.Thread(
            target=worker_thread,
            args=(ai_config, task_queue, failed_queue, results),
            name=f"Worker-{ai_name}",
            daemon=True
        )
        t.start()
        threads.append(t)
    
    # 生产者：边发现文件边入队
    task_count = 0
    try:
        for text_file in save_text_path.glob("*.text"):
            if stop_event.is_set():
                break
                
            match = FILENAME_PATTERN.match(text_file.name)
            if not match:
                continue
                
            timestamp_str, up_name, title, bvid = match.groups()
            date_folder = timestamp_str.split('_', 1)[0]
            md_file_name = text_file.name.replace(".text", ".md")
            local_md_path = markdown_root / date_folder / md_file_name
            
            needs_fix = False
            original_content = ""
            
            if not local_md_path.exists():
                logger.info(f"检测到缺失 Markdown: {md_file_name}")
                needs_fix = True
                # 从 generate_md.py 复制的模板
                formatted_time = timestamp_str.replace('_', ' ').replace('-', ':', 2)
                video_link = f"https://www.bilibili.com/video/{bvid}"
                original_content = f"""# {title}

- **UP主**: {up_name}
- **BVID**: {bvid}
- **视频链接**: <{video_link}>
- **文件时间**: {formatted_time}

---

## tags



## 总结



## 视频文稿

{text_file.read_text(encoding='utf-8')}
"""
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
                    if is_ai_summary_error(summary_text):
                        logger.info(f"检测到无效 AI总结 (Error): {md_file_name}")
                        needs_fix = True
            
            if needs_fix:
                task = {
                    "text_file": text_file,
                    "md_file_name": md_file_name,
                    "local_md_path": local_md_path,
                    "original_content": original_content,
                    "timestamp_str": timestamp_str
                }
                # 使用带超时的 put，避免死锁
                while not stop_event.is_set():
                    try:
                        task_queue.put(task, timeout=1)
                        break
                    except queue.Full:
                        continue
                
                if stop_event.is_set():
                    break
                    
                task_count += 1
                logger.debug(f"任务入队: {md_file_name} (队列大小: {task_queue.qsize()})")
                
                # Debug 模式: 只入队 AI 数量个任务
                if debug_mode and task_count >= len(ai_list):
                    logger.info(f"Debug模式: 已入队 {task_count} 个任务，停止扫描")
                    break
    
    except Exception as e:
        logger.error(f"生产者发生错误: {e}")
    
    # 标记生产者已完成
    producer_done.set()
    logger.info(f"文件扫描完成, 共发现 {task_count} 个待修复文件")
    
    if task_count == 0:
        logger.info("没有需要修复的文件")
        stop_event.set()  # 通知工作线程退出
        return
    
    # 等待所有线程完成 (支持 Ctrl+C 中断)
    try:
        for t in threads:
            while t.is_alive():
                t.join(timeout=0.5)
    except KeyboardInterrupt:
        logger.warning("收到中断信号，正在停止所有工作线程...")
        stop_event.set()
        # 等待线程优雅退出
        for t in threads:
            t.join(timeout=2)
        logger.info("所有线程已停止")
        return
    
    # 汇总结果
    total_success = sum(r.get("success", 0) for r in results.values())
    total_fail = sum(r.get("fail", 0) for r in results.values())
    
    logger.info(f"=" * 50)
    logger.info(f"修复完成: 成功 {total_success}, 失败 {total_fail}")
    
    # 列出失败的文件
    if not failed_queue.empty():
        logger.warning("以下文件修复失败，已回到未处理状态:")
        while not failed_queue.empty():
            failed_task = failed_queue.get()
            logger.warning(f"  - {failed_task['md_file_name']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="修复缺失或无效的 AI 总结")
    parser.add_argument("--debug", action="store_true", help="Debug模式: 每个 AI 只处理一个任务")
    args = parser.parse_args()
    
    if args.debug:
        debug_mode = True
        logger.info("Debug模式已启用: 每个 AI 只处理一个任务")
    
    fix_summaries()
    logger.info("修复任务执行完毕。")
