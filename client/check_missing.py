#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import re
import json

from bootstrap import get_standard_logger, SAVE_NEW_VIDEO_LIST_DIR, SAVE_TEXT_DIR, TEMP_DIR

# 日志
logger = get_standard_logger(__file__)

def get_bv_lines_from_files(file_list):
    """从文件列表中读取所有行并提取 BV 号"""
    all_lines = []
    bv_pattern = re.compile(r'BV[a-zA-Z0-9]{10}')
    
    for file_path in file_list:
        if not file_path.exists():
            continue
        try:
            with file_path.open('r', encoding='utf-8') as f:
                for line in f:
                    stripped_line = line.strip()
                    if stripped_line:
                        match = bv_pattern.search(stripped_line)
                        bv_code = match.group(0) if match else None
                        all_lines.append((stripped_line, bv_code))
        except Exception as e:
            logger.error(f"读取文件 '{file_path}' 时发生错误: {e}")
            
    return all_lines

def get_text_filenames(dir_path):
    """获取指定目录中所有 .text 文件的文件名"""
    filename_list = [path.name for path in dir_path.glob('*.text')]
    
    if not filename_list:
        logger.info(f"在目录 '{dir_path}' 中未找到任何 .text 文件。")
    
    return filename_list

def check_missing():
    """比较列表文件的 bvid 和已处理文本文件的 bvid，找出缺失的文本文件"""
    text_filename_list = get_text_filenames(SAVE_TEXT_DIR)

    new_video_list_files = [f for f in SAVE_NEW_VIDEO_LIST_DIR.iterdir() if f.is_file() and f.name != 'ignore.txt']
    all_lines_with_bv = get_bv_lines_from_files(new_video_list_files)
    
    ignore_file = SAVE_NEW_VIDEO_LIST_DIR / "ignore.txt"
    ignore_bvs = {bv for _, bv in get_bv_lines_from_files([ignore_file]) if bv}

    if not all_lines_with_bv:
        logger.info("没有需要检查的视频列表。")
        return

    logger.info("\n--- 开始检查缺失的BV号 ---")
    missing_bvs = []
    
    for line, bv in all_lines_with_bv:
        if not bv:
            continue
            
        # 检查 BV 号是否存在于任何一个文件名中
        is_present = any(bv in filename for filename in text_filename_list)
    
        if is_present or bv in ignore_bvs:
            continue
            
        # 检查 status 是否为 normal
        try:
            bv_info = json.loads(line)
            if bv_info.get("status") == "normal":
                missing_bvs.append((line, bv))
                logger.info(f"缺失的BV号: {bv} (对应行: {line})")
        except json.JSONDecodeError:
            logger.debug(f"无法解析行内容为JSON: {line[:50]}...")
                        
    # 报告结果
    if not missing_bvs:
        logger.info("\n[检查完成] 所有BV号都已处理或在忽略列表中。")
    else:
        logger.info(f"\n[检查完成] 发现 {len(missing_bvs)} 个缺失的BV号。")

        # 保存缺失的 BV 号原始行到文件
        output_filename = TEMP_DIR / "missing_input"
        try:
            with output_filename.open('w', encoding='utf-8') as f_out:
                for line, bv in missing_bvs:
                    f_out.write(line + '\n')
            logger.info(f"\n[成功] 已将 {len(missing_bvs)} 个缺失条目保存到文件: {output_filename}")
        except Exception as e:
            logger.error(f"保存文件时出错: {e}")
                
if __name__ == "__main__":
    check_missing()