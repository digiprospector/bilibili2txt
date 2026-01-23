#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from pathlib import Path
import sys
import shutil
import json
import yt_dlp

from bootstrap import config, get_standard_logger, QUEUE_DIR, TEMP_DIR

# Import git utils and webdav (libs added by bootstrap)
from git_utils import set_logger as git_utils_set_logger
from webdav import upload_to_webdav_requests, list_webdav_files

# Setup logger
logger = get_standard_logger(__file__)
git_utils_set_logger(logger)

def check_webdav_exists(bvid, webdav_files):
    """检查 WebDAV 上是否已存在该视频的音频文件"""
    if webdav_files is None:
        return False
        
    # 只要 WebDAV 上有任何以 bvid 开头的文件，就认为已存在
    # 这样可以处理 _NA.mp3, _1.mp3, _01.mp3 等各种情况
    for filename in webdav_files:
        if filename.startswith(bvid):
            logger.info(f"WebDAV上已存在文件: {filename}，跳过下载和上传。")
            return True
    return False

def download_audio(bvid, video_url):
    """下载视频音频"""
    output_audio_template = TEMP_DIR / f"{bvid}_%(playlist_index)s"
    
    ydl_opts = {
        'format': 'ba/bestaudio',
        'outtmpl': str(output_audio_template),
        'retries': 10,
        'continuedl': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }
    
    try:
        logger.info(f"开始下载视频音频: {video_url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        return True
    except Exception as e:
        logger.error(f"下载视频 {bvid} 失败: {e}")
        return False

def upload_parts(bvid, webdav_files):
    """上传下载好的音频分片到 WebDAV"""
    uploaded_any = False
    for local_path in TEMP_DIR.glob(f"{bvid}_*.mp3"):
        if local_path.exists():
            logger.info(f"准备上传到 WebDAV: {local_path.name}")
            upload_successful = upload_to_webdav_requests(
                url=f"{config['webdav_url']}/{local_path.name}",
                username=config['webdav_username'],
                password=config['webdav_password'],
                file_path=local_path,
                logger=logger,
                webdav_proxy=config.get('webdav_proxy')
            )
            if upload_successful:
                local_path.unlink()
                logger.info(f"已删除本地临时文件: {local_path.name}")
                if webdav_files is not None:
                    webdav_files.add(local_path.name)
                uploaded_any = True
            else:
                logger.error(f"上传失败: {local_path.name}")
    return uploaded_any

def process_video_info(bv_info, webdav_files):
    """处理单个视频信息"""
    bvid = bv_info.get('bvid')
    title = bv_info.get('title')
    status = bv_info.get('status')
    duration = bv_info.get('duration', 0)
    
    if status != "normal":
        logger.debug(f"视频 [{bvid}] 状态是{status}, 跳过")
        return False

    duration_limit = config.get("local_download_audio_seconds", 1800)
    if duration <= duration_limit:
        return False

    logger.info(f"找到符合条件的视频: [{bvid}] {title} (时长: {duration}s)")

    if check_webdav_exists(bvid, webdav_files):
        return True

    video_url = f"https://www.bilibili.com/video/{bvid}"
    if download_audio(bvid, video_url):
        if upload_parts(bvid, webdav_files):
            return True
    
    return False

def local_download_and_upload_to_webdav():
    """
    遍历to_stt目录, 寻找时长 > local_download_audio_seconds 的视频, 下载其音频并上传到WebDAV.
    """
    src_dir = QUEUE_DIR / "to_stt"
    
    try:
        webdav_files = list_webdav_files(
            config['webdav_url'], 
            config['webdav_username'], 
            config['webdav_password'], 
            logger, 
            config.get('webdav_proxy')
        )
    except Exception as e:
        logger.error(f"无法获取 WebDAV 文件列表: {e}")
        webdav_files = set()

    input_files = sorted([f for f in src_dir.glob("*") if not f.name.startswith(".") and f.is_file()])
    if not input_files:
        logger.info(f"{src_dir} 目录中没有待处理的文件，退出。")
        return
    
    found_and_processed = False
    for file_path in input_files:
        logger.info(f"正在扫描文件: {file_path.name}")
        try:
            content = file_path.read_text(encoding='utf-8')
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    bv_info = json.loads(line)
                    if process_video_info(bv_info, webdav_files):
                        found_and_processed = True
                except json.JSONDecodeError:
                    logger.warning(f"无法解析 JSON 行: {line[:50]}...")
                    continue
        except Exception as e:
            logger.error(f"读取文件 {file_path.name} 失败: {e}")
            continue
        
    if not found_and_processed:
        logger.info(f"没有找到需要下载的视频（时长 > {config.get('local_download_audio_seconds', 1800)}s）。")

    # 删除temp目录下的音频文件
    for file_path in TEMP_DIR.glob("*.mp3"):
        file_path.unlink()

if __name__ == "__main__":
    local_download_and_upload_to_webdav()
