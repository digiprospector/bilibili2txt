
from pathlib import Path
import shutil
import json
import time
import subprocess
from datetime import datetime, timezone, timedelta
import sys

SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))
from dp_logging import setup_logger
from dp_bilibili_api import dp_bilibili, download_file_with_resume

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

from config import config

TEMP_DIR = get_dir_in_config("temp_dir")
TEMP_MP3 = TEMP_DIR / "audio.mp3"
TEMP_SRT = TEMP_MP3.with_suffix(".srt")
TEMP_TEXT = TEMP_MP3.with_suffix(".text")
TEMP_TXT = TEMP_MP3.with_suffix(".txt")
FAST_WHISPER = config.get("server_faster_whisper_path")
OUTPUT_DIR = TEMP_DIR / "server_text"
def fetch_audio_link_from_json(bv_info):
    dp_blbl = dp_bilibili(logger=logger)
    dl_url = dp_blbl.get_audio_download_url(bv_info['bvid'], bv_info['cid'])
    logger.info(f"视频 {bv_info['title']} 的下载链接: {dl_url}")
    logger.info(f"正在下载 {dl_url} 到 {TEMP_MP3}")
    download_file_with_resume(dp_blbl.session, dl_url, TEMP_MP3)

def process_input():
    bv_list_file = TEMP_DIR / "bv_list.txt"

    # 启动时检查文件是否存在。如果不存在，则创建示例文件并退出。
    if not bv_list_file.exists():
        print(f"错误：未找到输入文件 '{bv_list_file}'。")
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
            print('没有找到有效行，所有任务处理完毕，退出。')
            break

        # 删除已处理的这一行，并保存回文件
        lines.remove(line_with_newline)
        with open(bv_list_file, 'w', encoding='utf-8') as f:
            f.writelines(lines)
    
        line = line_with_newline.strip()

        print("-" * 40)
        print(f"开始处理: {line}")
        try:
            print("--- 开始删除音频文件 ---")
            try:
                TEMP_MP3.unlink()
                print(f"已删除音频文件: {TEMP_MP3}")
            except FileNotFoundError:
                pass  # 文件不存在，是正常情况
            except Exception as e:
                print(f"删除音频文件 {TEMP_MP3} 时出错: {e}")
            # 步骤 1: 下载音频
            print(f"开始下载: {line}")
            try:
                bv_info = json.loads(line)
                print(f'该行是有效的 JSON 字符串。{bv_info.get("bvid")}, {bv_info.get("cid")}')
                if bv_info['status'] == 'normal':
                    fetch_audio_link_from_json(bv_info)
                else:
                    print(f"状态是{bv_info['status']}, 跳过")
                    continue
            except json.JSONDecodeError:
                print("该行不是有效的 JSON 字符串。")
                continue
            except Exception as e:
                print(f"处理 {line} 时出错: {e}")
                continue
                
            # 步骤 2: 调用 faster-whisper-xxl 处理音频
            if TEMP_MP3.exists():
                print("--- 开始删除转换后的文本文件 ---")
                try:
                    TEMP_SRT.unlink()
                    TEMP_TXT.unlink()
                    TEMP_TEXT.unlink()
                except FileNotFoundError:
                    pass  # 文件不存在，是正常情况
                except Exception as e:
                    print(f"删除文本文件时出错: {e}")
                print(f"--- 开始使用 faster-whisper-xxl 转录音频 ---")
                whisper_command = [
                    FAST_WHISPER,
                    TEMP_MP3,
                    '-m', 'large-v2',
                    '-l', 'Chinese',
                    '--vad_method', 'pyannote_v3',
                    '--ff_vocal_extract', 'mdx_kim2',
                    '--sentence',
                    '-v', 'true',
                    '-o', 'source',
                    '-f', 'txt', 'srt', 'text'
                ]
                subprocess.run(whisper_command, check=True)
                print("--- 音频转录完成 ---")
            else:
                print(f"警告: 未找到音频文件 '{TEMP_MP3}'，跳过转录步骤。")
                continue

            print(f"--- 开始复制生成的文本文件 ---")
            title = bv_info['title']
            invalid_chars = '<>:"/\\|?*'
            sanitized_title = title.translate(str.maketrans(invalid_chars, '_' * len(invalid_chars)))[0:50]
            # 将B站API返回的UTC时间戳转换为东八区（UTC+8）时间
            dt_utc8 = datetime.fromtimestamp(bv_info['pubdate'], tz=timezone(timedelta(hours=8)))
            fn = f"[{dt_utc8.strftime('%Y-%m-%d_%H-%M-%S')}][{bv_info['up_name']}][{sanitized_title}][{bv_info['bvid']}]"
            output_srt = OUTPUT_DIR / f"{fn}.srt"
            output_txt = output_srt.with_suffix('.txt')
            output_text = output_srt.with_suffix('.text')
            shutil.copy(TEMP_SRT, output_srt)
            shutil.copy(TEMP_TXT, output_txt)
            shutil.copy(TEMP_TEXT, output_text)            
            print(f"已复制生成的文本文件到 {OUTPUT_DIR}")
            
        except Exception as e:
            print(f"处理 {line} 时出错: {e}")
        
        time.sleep(10)

if __name__ == "__main__":
    process_input()