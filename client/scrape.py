#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import json
import time
import sqlite3
import argparse
import sys

# Ensure common is in path to import env
SCRIPT_DIR = Path(__file__).resolve().parent
COMMON_DIR = SCRIPT_DIR.parent / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.append(str(COMMON_DIR))

# Import environment context (config, logger, paths)
try:
    from env import config, setup_logger, get_path
except ImportError:
    print("Error: Could not import 'env' from common.")
    sys.exit(1)

# Import from libs (libs is added to path by env)
from dp_bilibili_api import dp_bilibili

# 日志
logger = setup_logger(Path(__file__).stem, log_dir=SCRIPT_DIR.parent / "logs")

USERDATA_DIR = get_path("userdata_dir")
DB_FILE = USERDATA_DIR / "bilibili_videos.db"
TARGET_GROUPS = config.get("target_group", [])
if isinstance(TARGET_GROUPS, str):
    TARGET_GROUPS = [TARGET_GROUPS]
DEBUG = config.get("debug", False)
TEMP_DIR = get_path("temp_dir")
NEW_VIDEO_LIST_DIR = get_path("new_video_list_dir")
COOKIES_FILE = USERDATA_DIR / "bili_cookies.json"


def setup_database():
    """初始化数据库和表，并处理可能的架构更新"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # 创建视频表，使用bvid作为主键防止重复
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            bvid TEXT PRIMARY KEY,
            up_name TEXT NOT NULL,
            up_mid INTEGER NOT NULL,
            title TEXT NOT NULL,
            link TEXT NOT NULL,
            pubdate INTEGER,
            duration INTEGER,
            cid INTEGER,
            status TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 检查并添加缺失的列 (用于旧版本数据库迁移)
    cursor.execute("PRAGMA table_info(videos)")
    columns = [column[1] for column in cursor.fetchall()]
    needed_columns = [
        ("pubdate", "INTEGER"),
        ("duration", "INTEGER"),
        ("cid", "INTEGER"),
        ("status", "TEXT")
    ]
    for col_name, col_type in needed_columns:
        if col_name not in columns:
            logger.info(f"数据库更新: 添加列 {col_name}")
            cursor.execute(f"ALTER TABLE videos ADD COLUMN {col_name} {col_type}")
            
    conn.commit()
    conn.close()

def video_exist_in_database(conn: sqlite3.Connection, bvid: str):
    """检查视频是否已存在"""
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM videos WHERE bvid = ?", (bvid,))
    return cursor.fetchone() is not None
    
def save_video_to_database(conn: sqlite3.Connection, video_info: dict):
    """保存视频到数据库"""
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO videos (bvid, up_name, up_mid, title, link, pubdate, duration, cid, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            video_info['bvid'],
            video_info['up_name'],
            video_info['up_mid'],
            video_info['title'],
            video_info['link'],
            video_info.get('pubdate'),
            video_info.get('duration'),
            video_info.get('cid'),
            video_info.get('status')
        ))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"保存视频到数据库时发生错误: {e}")
        return False

def process_video(conn, dp_blbl, video_info, all_new_videos):
    """处理单个视频的通用逻辑"""
    bvid = video_info['bvid']
    if not video_exist_in_database(conn, bvid):
        logger.info(f"      [新视频] {video_info['title']}")
        # 获取详细信息
        details = dp_blbl.get_video_info(bvid)
        if details:
            video_info.update(details)
        
        if save_video_to_database(conn, video_info):
            all_new_videos.append(video_info)
            time.sleep(config.get('request_interval', 1))
            return True
    return False

def process_up(conn, dp_blbl, up_mid, up_name, all_new_videos, max_pages=1):
    """处理指定UP主的视频"""
    page_num = 1
    page_size = 30
    
    while page_num <= max_pages:
        if max_pages > 1:
            logger.info(f"正在获取UP主 {up_name} 的视频列表，第 {page_num} 页...")
        
        videos = dp_blbl.get_videos_in_up(up_mid, ps=page_size, pn=page_num)
        if not videos:
            if max_pages > 1:
                logger.info(f"获取完毕。")
            break

        for bvid, details in videos.items():
            video_info = {
                "up_name": up_name, "up_mid": up_mid, "bvid": bvid, 
                "title": details['title'], "link": f"https://www.bilibili.com/video/{bvid}"
            }
            process_video(conn, dp_blbl, video_info, all_new_videos)
        
        page_num += 1
            
def get_bilibili_client():
    """初始化 dp_bilibili 实例并登录"""
    cookies = {}
    if COOKIES_FILE.exists():
        with open(COOKIES_FILE, "r") as f:
            cookies = json.load(f)
    dp_blbl = dp_bilibili(cookies=cookies, logger=logger)
    if dp_blbl.login():
        with open(COOKIES_FILE, "w") as f:
            json.dump(dp_blbl.session.cookies.get_dict(), f)
        return dp_blbl
    else:
        logger.warning("未登录, 退出")
        return None

def scrape(target_up_mid=None) -> str | None:
    # 获取目标分组
    logger.debug(f"目标分组: {TARGET_GROUPS}")
    
    # 初始化 dp_bilibili 实例并登录
    dp_blbl = get_bilibili_client()
    if not dp_blbl:
        return None
            
    
    # 初始化数据库
    setup_database()
    conn = sqlite3.connect(DB_FILE)

    all_new_videos = []

    try:
        if target_up_mid:
            # 处理单个UP主
            up_info = dp_blbl.get_up_info(target_up_mid)
            up_name = up_info.get('name', f'mid_{target_up_mid}')
            logger.info(f"开始处理指定UP主: {up_name} (MID: {target_up_mid})")
            process_up(conn, dp_blbl, target_up_mid, up_name, all_new_videos, max_pages=100)
        else:
            # 获取关注分组
            following_groups = dp_blbl.get_following_groups()
            logger.debug(f"关注分组: {following_groups}")
            
            # 遍历目标分组
            for group_name_to_find in TARGET_GROUPS:
                found_group = False
                for follow_group_id, group_info in following_groups.items():
                    follow_group_name = group_info['name']
                    if group_name_to_find == follow_group_name:
                        found_group = True
                        follow_group_ups_count = group_info['count']
                        logger.info(f"正在处理分组: {follow_group_name} (ID: {follow_group_id}, UP主个数: {follow_group_ups_count})")
                        ups = dp_blbl.get_ups_in_group(follow_group_id)
                        
                        for i, (up_mid, up_info) in enumerate(ups.items(), 1):
                            up_name = up_info['name']
                            logger.info(f"[{i}/{follow_group_ups_count}] UP主: {up_name}")
                            process_up(conn, dp_blbl, up_mid, up_name, all_new_videos, max_pages=1)
                            
                            if DEBUG and i >= 1:
                                logger.debug("DEBUG 模式，跳出 UP 主循环")
                                break
                if not found_group:
                    logger.warning(f"未找到名为 '{group_name_to_find}' 的关注分组")
    finally:
        conn.close()
    
    logger.info("-------------------------------------\n")
    if all_new_videos:
        # 按长度排序
        all_new_videos.sort(key=lambda v: v['duration'])
        
        new_videos_count = len(all_new_videos)
        current_time = time.strftime("%Y%m%d-%H%M%S")
        output_filename = NEW_VIDEO_LIST_DIR / f"new_videos_{current_time}.txt"

        # 写入文件
        with open(output_filename, 'w', encoding='utf-8') as f:
            for video in all_new_videos:
                line = json.dumps(video, ensure_ascii=False) + "\n"
                f.write(line)
        
        logger.info(f"检查完成，共发现 {new_videos_count} 个符合条件的视频。")
        logger.info(f"新视频列表已保存到 {output_filename}")
        logger.info(f"所有视频历史记录已更新到 {DB_FILE}")
        return output_filename
    else:
        logger.info("所有指定分组或UP主检查完成，没有发现符合条件的视频。")
        return None
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从Bilibili关注分组或指定UP主那里抓取视频信息。")
    parser.add_argument(
        "--up-mid",
        type=int,
        help="指定要抓取的单个UP主的MID。"
    )
    args = parser.parse_args()

    scrape(target_up_mid=args.up_mid)