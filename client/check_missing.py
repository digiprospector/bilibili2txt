#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import sys
import shutil
import re
import json

SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))
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
    return dir_path

from config import config

SAVE_NEW_VIDEO_LIST_DIR = get_dir_in_config("save_new_video_list_dir")
SAVE_TEXT_DIR = get_dir_in_config("save_text_dir")
TEMP_DIR = get_dir_in_config("temp_dir")

def get_bv_lines_from_files(file_list):
    all_lines = []
    for file_path in file_list:
        try:
            # Path 对象有自己的 open 方法，可以直接调用
            # 使用 encoding='utf-8' 来更好地处理包含非英文字符的文件
            with file_path.open('r', encoding='utf-8') as f:
                processed_lines = []
                for line in f:
                    stripped_line = line.strip()
                    if stripped_line:
                        # 查找 BV 开头的12位字符串 (BV + 10个字符)
                        match = re.search(r'BV[a-zA-Z0-9]{10}', stripped_line)
                        bv_code = match.group(0) if match else None
                        processed_lines.append((stripped_line, bv_code))
                all_lines.extend(processed_lines)
        except Exception as e:
            logger.info(f"错误：读取文件 '{file_path}' 时发生错误: {e}")
            
    return all_lines

def get_text_filenames(dir_path):
    """
    获取指定目录中所有 .text 文件的文件名，并存入一个列表。

    Args:
        directory (str or Path): 要搜索的目录路径。默认为当前目录。

    Returns:
        list[str]: 包含所有 .text 文件名的列表。
    """
    
    # 使用 .glob() 查找所有 .text 文件，然后用列表推导式提取文件名
    # path.name 只返回文件名（例如 'input.text'）
    filename_list = [path.name for path in dir_path.glob('*.text')]
    
    if not filename_list:
        # 使用 .resolve() 获取绝对路径，使输出信息更明确
        logger.info(f"信息：在目录 '{dir_path.resolve()}' 中未找到任何 .text 文件。")
    
    return filename_list

def check_missing():
    # 比较列表文件的bvid和已处理文本文件的bvid,找出缺失的文本文件

    text_filename_list = get_text_filenames(SAVE_TEXT_DIR)

    new_video_list_files = [f for f in SAVE_NEW_VIDEO_LIST_DIR.iterdir() if f.is_file() and f.name != 'ignore.txt']
    all_lines_with_bv = get_bv_lines_from_files(new_video_list_files)
    ignore_lines_with_bv = get_bv_lines_from_files([SAVE_NEW_VIDEO_LIST_DIR/"ignore.txt"])

    if all_lines_with_bv:
        logger.info("\n--- 开始检查缺失的BV号 ---")
        missing_bvs = []
        
        # 3. 遍历所有提取到的行和BV号
        for line, bv in all_lines_with_bv:
            # 只处理成功提取到BV号的行
            if bv:
                # 检查BV号是否存在于任何一个文件名中
                is_present = any(bv in filename for filename in text_filename_list)
        
                if not is_present:
                    # 在ignore list里面
                    ignore_this_bv = False
                    for ignore_line, ignore_bv in ignore_lines_with_bv:
                        if ignore_bv == bv:
                            ignore_this_bv = True
                            break
                    
                    if not ignore_this_bv:
                        # 如果不存在, 看看status是不是normal
                        try:
                            bv_info = json.loads(line.strip())
                            if bv_info["status"] == "normal":
                                missing_bvs.append((line, bv))
                                logger.info(f"缺失的BV号: {bv} (对应行: {line})")
                        except Exception as e:
                            logger.debug(f"无法解析行内容为JSON: {line} {e}")
                            
        # 4. 报告最终结果
        if not missing_bvs:
            logger.info("\n[检查完成] 所有从文件中提取的BV号都已在至少一个文件名中找到。")
        else:
            logger.info(f"\n[检查完成] 发现 {len(missing_bvs)} 个缺失的BV号（即BV号存在于文件内容中，但不存在于任何文件名中）：")
            for line, bv in missing_bvs:
                #logger.info(f"  - BV号: {bv} (来源: '{line}')")
                pass

            # 5. 将缺失的BV号原始行保存到文件
            output_filename = TEMP_DIR / "missing_input"
            try:
                with output_filename.open('w', encoding='utf-8') as f_out:
                    for line, bv in missing_bvs:
                        f_out.write(line + '\n')
                logger.info(f"\n[成功] 已将 {len(missing_bvs)} 个缺失条目保存到文件: {output_filename}")
            except Exception as e:
                logger.info(f"\n[错误] 保存文件时出错: {e}")
                        
                
if __name__ == "__main__":
    check_missing()