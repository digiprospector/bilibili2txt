#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from pathlib import Path
import sys
import shutil
import json
import requests
from xml.etree import ElementTree
import yt_dlp

SCRIPT_DIR = Path(__file__).parent
sys.path.append(str(SCRIPT_DIR.parent.absolute())) # 导入 upload.py
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))
from dp_logging import setup_logger
from git_utils import set_logger as git_utils_set_logger
from webdav import upload_to_webdav_requests, check_webdav_file_exists
# 日志
logger = setup_logger(Path(__file__).stem, log_dir=SCRIPT_DIR.parent / "logs")
git_utils_set_logger(logger)

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
QUEUE_DIR = get_dir_in_config("queue_dir")
TEMP_DIR = get_dir_in_config("temp_dir")

def list_webdav_files(url, username, password, logger, webdav_proxy=None):
    """获取WebDAV服务器上指定路径下的文件列表"""
    logger.info(f"正在从 WebDAV 获取文件列表: {url}")
    proxies = {'http': webdav_proxy, 'https': webdav_proxy} if webdav_proxy else None
    try:
        response = requests.request(
            "PROPFIND",
            url,
            auth=(username, password),
            headers={"Depth": "1"},
            proxies=proxies,
            timeout=30
        )
        response.raise_for_status()
        
        # 解析XML响应
        root = ElementTree.fromstring(response.content)
        # 命名空间通常是 {DAV:}
        ns = {'d': 'DAV:'}
        filenames = [Path(href.text).name for href in root.findall('.//d:href', ns)]
        logger.info(f"从 WebDAV 成功获取 {len(filenames)} 个文件。")
        return set(filenames)
    except requests.exceptions.RequestException as e:
        logger.error(f"从 WebDAV 获取文件列表失败: {e}")
        return None

def local_download_and_upload_to_webdav():
    """
    遍历to_stt目录, 寻找时长 > local_download_audio_seconds 的视频, 下载其音频并上传到WebDAV.
    """
    src_dir = QUEUE_DIR / "to_stt"
    webdav_files = list_webdav_files(config['webdav_url'], config['webdav_username'], config['webdav_password'], logger, config.get('webdav_proxy'))
    
    input_files = sorted([f for f in src_dir.glob("*") if not f.name.startswith(".") and f.is_file()])
    if not input_files:
        logger.info(f"{src_dir} 目录中没有待处理的文件，退出。")
        return
    
    found_and_processed = False
    for file_path in input_files:
        lines = file_path.read_text(encoding='utf-8').splitlines()
        if not lines:
            logger.info(f"文件 {file_path.name} 为空，跳过。")
            continue

        line_to_process = None

        # 查找符合条件的行
        for i, line in enumerate(lines):
            try:
                bv_info = json.loads(line)
                if bv_info.get("status") != "normal":
                    logger.info(f"状态是{bv_info['status']}, 跳过")
                    continue
                duration_limit = config.get("local_download_audio_seconds", 1800)
                if bv_info.get("duration", 0) > duration_limit:
                    line_to_process = line
                    bv_info = json.loads(line_to_process)
                    bvid = bv_info['bvid']
                    title = bv_info['title']
                    logger.info(f"找到时长 > {duration_limit}s 的视频: [{bvid}] {title}，开始处理...")
                    
                    # 检查WebDAV上是否已存在该文件，如果存在则跳过
                    filenames_to_check = [
                        f"{bvid}_NA.mp3",  # 单个文件
                        f"{bvid}_1.mp3",   # 合集分P (从1开始)
                        f"{bvid}_01.mp3"  # 合集分P (从01开始)
                    ]
                    file_exists = False
                    for filename in filenames_to_check:
                        if webdav_files is not None and filename in webdav_files:
                            logger.info(f"WebDAV上已存在文件: {filename}，跳过下载和上传。")
                            file_exists = True
                            break
                    if file_exists:
                        continue

                    # 1. 下载音频
                    video_url = f"https://www.bilibili.com/video/{bvid}"
                    # 使用bvid作为文件名，避免特殊字符问题
                    output_audio_path = TEMP_DIR / f"{bvid}.mp3"
                    
                    ydl_opts = {
                        'format': 'ba/bestaudio',
                        'outtmpl': str(TEMP_DIR / f"{output_audio_path.stem}_%(playlist_index)s{output_audio_path.suffix}"),
                        'retries': 10,
                        'continuedl': True,
                    }
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([video_url])

                    # 2. 上传到WebDAV
                    for output_audio_path in TEMP_DIR.glob(f"{bvid}_*.mp3"):
                        if output_audio_path.exists():
                            logger.info(f"音频下载完成: {output_audio_path}，准备上传到WebDAV...")
                            upload_successful = upload_to_webdav_requests(
                                url=f"{config['webdav_url']}/{output_audio_path.name}",
                                username=config['webdav_username'],
                                password=config['webdav_password'],
                                file_path=output_audio_path,
                                logger=logger,
                                webdav_proxy=config.get('webdav_proxy')
                            )
                            if upload_successful:
                                # 上传后删除本地临时文件
                                output_audio_path.unlink()
                                logger.info(f"已删除本地临时文件: {output_audio_path}")
                                if webdav_files is not None:
                                    webdav_files.add(output_audio_path.name)
                        else:
                            logger.error(f"下载失败，未找到音频文件: {output_audio_path}")
                            # 下载失败，跳过此视频的处理
                            continue
                                        
                    found_and_processed = True
                    

            except json.JSONDecodeError:
                logger.warning(f"无法解析行内容为JSON，跳过: {line}")
                continue
        
    if not found_and_processed:
        logger.info("所有文件中未找到时长 > 1800s 的视频。")

if __name__ == "__main__":
    local_download_and_upload_to_webdav()