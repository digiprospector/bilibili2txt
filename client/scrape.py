#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import json
import shutil
import time
import sqlite3
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
USERDATA_DIR = get_dir_in_config("userdata_dir")
DB_FILE = USERDATA_DIR / "bilibili_videos.db"
TARGET_GROUPS = config["target_group"]
if isinstance(TARGET_GROUPS, str):
    TARGET_GROUPS = [TARGET_GROUPS]
DEBUG = config["debug"]
TEMP_DIR = get_dir_in_config("temp_dir")
NEW_VIDEO_LIST_DIR = get_dir_in_config("new_video_list_dir")

def setup_database():
    """初始化数据库和表"""
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
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def video_exist_in_database(conn: sqlite3.Connection, bvid: str):
    """安全的键存在检查"""
    cursor = conn.cursor()
    query = f"SELECT COUNT(*) FROM videos WHERE bvid = ?"
    cursor.execute(query, (bvid,))
    count = cursor.fetchone()[0]
    return count > 0
    
def save_video_to_database_if_not_exists(conn: sqlite3.Connection, video_info: dict):
    """如果视频不存在，则保存到数据库并返回True，否则返回False。"""
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO videos (bvid, up_name, up_mid, title, link, pubdate, duration, cid, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            video_info['bvid'],
            video_info['up_name'],
            video_info['up_mid'],
            video_info['title'],
            video_info['link'],
            video_info['pubdate'],
            video_info['duration'],
            video_info['cid'],
            video_info['status']
        ))
        conn.commit()
        return True  # 插入成功
    except sqlite3.IntegrityError:
        # bvid (主键) 已存在，忽略错误
        return False # 未插入
    except Exception as e:
        logger.error(f"保存视频到数据库时发生错误: {e}")
        return False # 保存失败
            
def scrape(target_up_mid=None):
    # 获取目标分组
    logger.debug(f"目标分组: {TARGET_GROUPS}")
    
    # 初始化 dp_bilibili 实例
    cookies = {}
    cookies_file = USERDATA_DIR / "bili_cookies.json"
    if cookies_file.exists():
        with open(cookies_file, "r") as f:
            cookies = json.load(f)
    dp_blbl = dp_bilibili(cookies=cookies, logger=logger)
    if dp_blbl.login():
        with open(cookies_file, "w") as f:
            json.dump(dp_blbl.session.cookies.get_dict(), f)
    else:
        logger.warning("未登录, 退出")
        return False
            
    # 获取关注分组
    following_groups = dp_blbl.get_following_groups()
    logger.debug(f"关注分组: {following_groups}")
    
    # 初始化数据库
    setup_database()
    conn = sqlite3.connect(DB_FILE)

    all_new_videos = []

    if target_up_mid:
        # 处理单个UP主
        logger.info(f"开始处理指定UP主: {target_up_mid}")
        up_info = dp_blbl.get_up_info(target_up_mid)
        up_name = up_info.get('name', f'mid_{target_up_mid}')
        logger.info(f"UP主: {up_name}")

        page_num = 1
        page_size = 30
        processed_count = 0
        total_videos = -1

        while True:
            logger.info(f"正在获取UP主 {up_name} 的视频列表，第 {page_num} 页...")
            videos = dp_blbl.get_videos_in_up(target_up_mid, ps=page_size, pn=page_num)
            if total_videos == -1:
                total_videos = len(videos)

            if not videos:
                logger.info(f"UP主 {up_name} 的所有视频页面已获取完毕。")
                break

            for bvid, video_details in videos.items():
                processed_count += 1
                title = video_details['title']
                logger.info(f"  ({processed_count}/{total_videos}) 正在处理: {title}")
                video_info = {"up_name": up_name, "up_mid": target_up_mid, "bvid": bvid, "title": title, "link": f"https://www.bilibili.com/video/{bvid}"}
                
                if not video_exist_in_database(conn, bvid):                
                    video_info.update(dp_blbl.get_video_info(bvid))
                    save_video_to_database_if_not_exists(conn, video_info)
                    all_new_videos.append(video_info)
                    time.sleep(config['request_interval'])
            page_num += 1
    else:
        # 遍历目标分组 (原有逻辑)
        for group in TARGET_GROUPS:
            for follow_group_id in following_groups:
                follow_group_name = following_groups[follow_group_id]['name']
                follow_group_ups_count = following_groups[follow_group_id]['count']
                if group == follow_group_name:
                    logger.info(f"正在处理分组: {follow_group_name} (ID: {follow_group_id}, 个数: {follow_group_ups_count})")
                    ups = dp_blbl.get_ups_in_group(follow_group_id)
                    logger.debug(f"分组 {follow_group_name} 中的UP主: {ups}")
                    c = 0
                    up_count = 1
                    for up_mid in ups:
                        any_new_video_in_this_up = False
                        up_name = ups[up_mid]['name']
                        logger.info(f"[{up_count}/{follow_group_ups_count}] UP主: {up_name}")
                        videos = dp_blbl.get_videos_in_up(up_mid) # 原有逻辑只取第一页
                        logger.debug(f"UP主 {up_name} 的视频列表: {videos}")
                        for bvid in videos:
                            title = videos[bvid]['title']
                            video_info = {
                                "up_name": up_name, "up_mid": up_mid, "bvid": bvid, "title": title,
                                "link": f"https://www.bilibili.com/video/{bvid}"
                            }
                            if not video_exist_in_database(conn, bvid):
                                video_info.update(dp_blbl.get_video_info(bvid)) # 获取详细信息
                                if save_video_to_database_if_not_exists(conn, video_info): # 保存到数据库
                                    logger.info(f"      [新视频] {video_info['title']}")
                                    all_new_videos.append(video_info)
                                any_new_video_in_this_up = True
                                time.sleep(config['request_interval'])
                        c += 1
                        up_count += 1
                        if DEBUG and c >= 1:
                            logger.debug("DEBUG 模式，跳出 UP 主循环")
                            break
                        
                        if not any_new_video_in_this_up:
                            logger.info(f"分组 {follow_group_name} 中的 UP 主 {up_name} 没有新视频。")
                            time.sleep(config['request_interval'])
    
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
    else:
        logger.info("所有指定分组或UP主检查完成，没有发现符合条件的视频。")
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从Bilibili关注分组或指定UP主那里抓取视频信息。")
    parser.add_argument(
        "--up-mid",
        type=int,
        help="指定要抓取的单个UP主的MID。"
    )
    args = parser.parse_args()

    scrape(target_up_mid=args.up_mid)