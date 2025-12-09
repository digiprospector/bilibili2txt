
from pathlib import Path
import shutil
import json
import time
import subprocess
from datetime import datetime, timezone, timedelta
import re

import sys

SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))
from dp_logging import setup_logger
from dp_bilibili_api import dp_bilibili
from webdav import download_from_webdav_requests

# 日志
logger = setup_logger(Path(__file__).stem, log_dir=SCRIPT_DIR.parent / "logs")

# Get the directory where the script is located
SCRIPT_DIR = Path(__file__).parent.resolve()

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

def get_path_in_config(key: str) -> Path:
    path_str = config[key]
    if path_str.startswith("/"):
        _path = Path(path_str)
    else:
        _path = SCRIPT_DIR.parent / path_str
    logger.debug(f"config[{key}] 的路径: {_path}")
    return _path

from config import config

TEMP_DIR = get_dir_in_config("temp_dir")
TEMP_MP3 = TEMP_DIR / "audio.mp3"
TEMP_SRT = TEMP_MP3.with_suffix(".srt")
TEMP_TEXT = TEMP_MP3.with_suffix(".text")
TEMP_TXT = TEMP_MP3.with_suffix(".txt")
FAST_WHISPER = get_path_in_config("server_faster_whisper_path")
OUTPUT_DIR = TEMP_DIR / "server_text"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

try:
    import yt_dlp
except ImportError:
    logger.error("yt-dlp 库未安装，请运行 'pip install yt-dlp'。")
    sys.exit(1)

def fetch_audio_link_from_json(bv_info):
    """
    获取音频文件。
    1. 优先尝试从WebDAV下载。
    2. 如果失败，则使用yt-dlp下载。
    返回一个包含已下载音频文件路径的列表。
    """
    duration = bv_info.get("duration", 0)
    bvid = bv_info['bvid']

    # 如果视频时长大于local_download_audio_seconds秒，优先尝试从WebDAV下载
    duration_limit = config.get("local_download_audio_seconds", 1800)
    
    if duration > duration_limit and bvid:
        logger.info(f"视频时长 {duration}s > {duration_limit}s，尝试从 WebDAV 智能查找并下载...")

        # 1. 优先尝试单个文件的命名格式: {bvid}_NA.mp3
        filename = f"{bvid}_NA.mp3"
        webdav_url = f"{config['webdav_url']}/{filename}"
        logger.info(f"尝试下载单个文件: {filename}")
        download_successful = download_from_webdav_requests(url=webdav_url, username=config['webdav_username'], password=config['webdav_password'], local_file_path=TEMP_MP3, logger=logger)
        if download_successful:
            #logger.info(f"从 WebDAV 成功下载音频: {filename}")
            #logger.info(f"开始从 WebDAV 删除文件: {filename}")
            #delete_from_webdav_requests(url=webdav_url, username=config['webdav_username'], password=config['webdav_password'], logger=logger)
            return [TEMP_MP3]

        # 2. 如果单个文件格式失败，则从1开始逐个尝试合集分P的文件
        logger.info(f"未找到 {filename}，开始尝试带1开始的,编号的合集文件...")
        downloaded_files_from_webdav = []
        for i in range(1, 100): # 尝试从 _1 到 _99
            filename = f"{bvid}_{i}.mp3"
            webdav_url = f"{config['webdav_url']}/{filename}"
            local_temp_file = TEMP_DIR / f"audio_{i}.mp3"

            # 在日志中减少冗余，只在第一次循环时提示
            if i == 1:
                logger.info(f"尝试下载: {filename} ...")
            
            download_successful = download_from_webdav_requests(url=webdav_url, username=config['webdav_username'], password=config['webdav_password'], local_file_path=local_temp_file, logger=logger)
            
            if download_successful:
                logger.info(f"从 WebDAV 成功下载音频: {filename}")
                downloaded_files_from_webdav.append(local_temp_file)
                #logger.info(f"开始从 WebDAV 删除文件: {filename}")
                #delete_from_webdav_requests(url=webdav_url, username=config['webdav_username'], password=config['webdav_password'], logger=logger)
            else:
                # 下载失败，意味着序列结束
                break

        # 2.1. 如果从1开始逐个尝试合集分P的文件，则从01开始逐个尝试合集分P的文件
        if not downloaded_files_from_webdav:
            logger.info(f"未找到 {filename}，开始尝试带01开始的,编号的合集文件...")
            for i in range(1, 100): # 尝试从 _01 到 _99
                filename = f"{bvid}_{i:02}.mp3"
                webdav_url = f"{config['webdav_url']}/{filename}"
                local_temp_file = TEMP_DIR / f"audio_{i}.mp3"

                # 在日志中减少冗余，只在第一次循环时提示
                if i == 1:
                    logger.info(f"尝试下载: {filename} ...")
                
                download_successful = download_from_webdav_requests(url=webdav_url, username=config['webdav_username'], password=config['webdav_password'], local_file_path=local_temp_file, logger=logger)
                
                if download_successful:
                    logger.info(f"从 WebDAV 成功下载音频: {filename}")
                    downloaded_files_from_webdav.append(local_temp_file)
                    #logger.info(f"开始从 WebDAV 删除文件: {filename}")
                    #delete_from_webdav_requests(url=webdav_url, username=config['webdav_username'], password=config['webdav_password'], logger=logger)
                else:
                    # 下载失败，意味着序列结束
                    break

        if downloaded_files_from_webdav:
            logger.info(f"从 WebDAV 共下载了 {len(downloaded_files_from_webdav)} 个文件。")
            return downloaded_files_from_webdav
        logger.info(f"在 WebDAV 上未找到匹配的音频文件，将回退使用 yt-dlp 下载。")

    # 如果WebDAV下载失败或不满足条件，则使用 yt-dlp
    video_url = f"https://www.bilibili.com/video/{bvid}"
    logger.info(f"开始使用 yt-dlp 下载视频 {bv_info['title']} ({bvid}) 的音频")
    
    # 为多P视频设置动态文件名模板
    output_template = TEMP_DIR / 'audio_%(playlist_index)s.mp3'
    
    ydl_opts = {
        'format': 'ba/bestaudio',  # 'ba' 代表 bestaudio
        'outtmpl': str(output_template),
        'retries': 20,
        'continuedl': True,
        'retry_sleep': {'http': 10, 'fragment': 10, 'hls': 10}
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])
    
    # 如果yt-dlp为单个视频生成了audio_NA.mp3，将其重命名为audio.mp3
    na_file = TEMP_DIR / 'audio_NA.mp3'
    if na_file.exists():
        target_file = TEMP_DIR / 'audio.mp3'
        na_file.rename(target_file)
        logger.info(f"已将 {na_file.name} 重命名为 {target_file.name}")
        logger.info(f"yt-dlp 下载完成，找到 1 个音频文件。")
        return [target_file]

    # 查找所有下载的音频文件并返回列表
    downloaded_files = sorted(TEMP_DIR.glob('audio_*.mp3'))
    # 检查是否存在单个视频文件（已被重命名或原本就是audio.mp3）
    logger.info(f"yt-dlp 下载完成，找到 {len(downloaded_files)} 个音频文件。")
    return downloaded_files

def process_input():
    bv_list_file = TEMP_DIR / "bv_list.txt"

    # 启动时检查文件是否存在。如果不存在，则创建示例文件并退出。
    if not bv_list_file.exists():
        logger.info(f"错误：未找到输入文件 '{bv_list_file}'。")
        return False
    
    while True:
        # 在每次循环开始时，都重新读取文件以获取最新内容
        with open(bv_list_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 寻找第一个有效行进行处理
        line_with_newline = None
        for current_line_obj in lines:
            if current_line_obj.strip() and not current_line_obj.strip().startswith('#'):
                line_with_newline = current_line_obj
                break

        # 如果没有找到有效行，说明所有任务都已处理完毕，退出循环
        if line_with_newline is None:
            logger.info('没有找到有效行，所有任务处理完毕，退出。')
            break

        # 删除已处理的这一行，并保存回文件
        lines.remove(line_with_newline)
        with open(bv_list_file, 'w', encoding='utf-8') as f:
            f.writelines(lines)
    
        line = line_with_newline.strip()

        logger.info("-" * 40)
        logger.info(f"开始处理: {line}")
        try:
            logger.info("--- 开始清理临时音频文件 ---")
            try:
                # 删除所有 audio*.mp3 和 audio*.mp3.part 文件
                for f in TEMP_DIR.glob('audio*.mp3*'):
                    f.unlink()
                    logger.info(f"已删除临时文件: {f.name}")
            except Exception as e:
                logger.error(f"清理临时音频文件时出错: {e}")

            # 步骤 1: 下载音频
            logger.info(f"开始下载: {line}")
            downloaded_audio_files = []
            try:
                bv_info = json.loads(line)
                logger.info(f'该行是有效的 JSON 字符串。{bv_info.get("bvid")}, {bv_info.get("cid")}')
                if bv_info.get('status') != 'normal':
                    logger.info(f"状态是{bv_info['status']}, 跳过")
                    continue
                downloaded_audio_files = fetch_audio_link_from_json(bv_info)
            except json.JSONDecodeError:
                logger.info("该行不是有效的 JSON 字符串。通过bvid获得信息.")
                stripped_line = line.strip()
                match = re.search(r'BV[a-zA-Z0-9]{10}', stripped_line)
                if match:
                    bvid = match.group(0)
                    dp_blbl = dp_bilibili(logger=logger)
                    bv_info = dp_blbl.get_video_info(bvid)
                    bv_info['bvid'] = bvid
                    logger.info(f"获得信息\n{bv_info=}")
                    downloaded_audio_files = fetch_audio_link_from_json(bv_info)
                else:
                    logger.info(f"这行没有bvid:{stripped_line}")
                    continue
            except Exception as e:
                logger.info(f"处理 {line} 时出错: {e}")
                continue
            
            if not downloaded_audio_files:
                logger.warning(f"未下载任何音频文件，跳过转录步骤。")
                continue

            # 步骤 2: 循环处理所有下载的音频文件
            for i, audio_file in enumerate(downloaded_audio_files):
                logger.info(f"--- 开始处理第 {i+1}/{len(downloaded_audio_files)} 个音频: {audio_file.name} ---")
                if audio_file.exists():
                    # 清理旧的转录结果
                    for suffix in ['.srt', '.txt', '.text']:
                        try:
                            audio_file.with_suffix(suffix).unlink()
                        except FileNotFoundError:
                            pass

                    logger.info(f"--- 开始使用 faster-whisper-xxl 转录音频 ---")
                    whisper_command = [
                        FAST_WHISPER, str(audio_file),
                        '-m', 'large-v2', '-l', 'Chinese',
                        '--vad_method', 'pyannote_v3', '--ff_vocal_extract', 'mdx_kim2',
                        '--sentence', '-v', 'true', '-o', 'source',
                        '-f', 'txt', 'srt', 'text'
                    ]
                    subprocess.run(whisper_command, check=True)
                    logger.info("--- 音频转录完成 ---")

                    logger.info(f"--- 开始复制生成的文本文件 ---")
                    title = bv_info['title']
                    invalid_chars = '<>:"/\\|?*'
                    sanitized_title = title.translate(str.maketrans(invalid_chars, '_' * len(invalid_chars)))[0:50]
                    dt_utc8 = datetime.fromtimestamp(bv_info['pubdate'], tz=timezone(timedelta(hours=8)))
                    
                    # 为多P文件添加后缀
                    p_suffix = f"_{i+1}" if len(downloaded_audio_files) > 1 else ""
                    fn = f"[{dt_utc8.strftime('%Y-%m-%d_%H-%M-%S')}][{bv_info['up_name']}][{sanitized_title}][{bv_info['bvid']}{p_suffix}]"
                    
                    # 从转录结果复制文件
                    for suffix in ['.srt', '.txt', '.text']:
                        src_file = audio_file.with_suffix(suffix)
                        if src_file.exists():
                            dst_file = OUTPUT_DIR / f"{fn}{suffix}"
                            shutil.copy(src_file, dst_file)
                    logger.info(f"已复制生成的文本文件到 {OUTPUT_DIR}")
                else:
                    logger.warning(f"未找到音频文件 '{audio_file}'，跳过。")
            
        except Exception as e:
            logger.info(f"处理 {line} 时出错: {e}")
        
        time.sleep(10)

if __name__ == "__main__":
    process_input()