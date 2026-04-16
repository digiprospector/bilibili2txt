#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import re
from pathlib import Path

from bootstrap import get_standard_logger, get_path, config
from ai_utils import AIConfigManager, analyze_stock_market, is_ai_response_error
from md_utils import extract_metadata_from_filename, update_or_add_ai_summary, build_markdown_content
from fix_ai_summary import update_netdisk_summary

# 日志
logger = get_standard_logger(__file__)

def main():
    parser = argparse.ArgumentParser(description="对指定的文章进行重新总结")
    parser.add_argument("-b", "--bvid", required=True, help="指定的 BVID")
    parser.add_argument("-a", "--ai", help="使用的 AI 名称 (可选，默认为 config.py 中的 select_open_ai)")
    args = parser.parse_args()

    bvid = args.bvid
    ai_name = args.ai or config.get("select_open_ai")

    # 1. 查找文稿文件
    save_text_dir = get_path("save_text_dir")
    logger.info(f"正在查找 BVID 为 {bvid} 的文稿 (搜索目录: {save_text_dir})...")
    
    target_files = list(save_text_dir.glob(f"*{bvid}*.text"))
    if not target_files:
        logger.error(f"未找到包含 BVID {bvid} 的 .text 文件")
        return

    text_file = target_files[0]
    logger.info(f"找到文稿文件: {text_file.name}")

    # 2. 解析元数据
    meta = extract_metadata_from_filename(text_file.name)
    if not meta:
        logger.error(f"无法从文件名解析元数据: {text_file.name}")
        return

    # 3. 获取 AI 配置
    ai_config = AIConfigManager.get_by_name(ai_name)
    if not ai_config:
        logger.error(f"未找到 AI 配置: {ai_name}")
        return
    
    actual_ai_name = ai_config.get("openai_api_name", ai_name)
    logger.info(f"使用 AI: {actual_ai_name} (模型: {ai_config.get('openai_model')})")

    # 4. 读取文稿并生成总结
    transcript = text_file.read_text(encoding='utf-8')
    logger.info("正在生成 AI 总结...")
    
    summary = analyze_stock_market(transcript, ai_config=ai_config)
    
    if is_ai_response_error(summary):
        logger.error(f"AI 生成总结失败: {summary}")
        return

    summary = summary.replace("**“", " **“")
    # 如果 AI 总结包含代码块标记，尝试清理（有些 AI 喜欢加 ```markdown ... ```）
    summary = re.sub(r'^```markdown\n', '', summary)
    summary = re.sub(r'\n```$', '', summary)
    
    logger.info("AI 总结生成完成。")

    # 5. 更新本地 Markdown 文件
    markdown_root = save_text_dir.parent / "markdown"
    md_file_name = text_file.name.replace(".text", ".md")
    local_md_path = markdown_root / meta["date_folder"] / md_file_name

    new_content = ""
    if local_md_path.exists():
        original_content = local_md_path.read_text(encoding='utf-8')
        new_content = update_or_add_ai_summary(original_content, summary, actual_ai_name)
        logger.info(f"正在更新本地 Markdown: {local_md_path}")
    else:
        logger.info(f"本地 Markdown 不存在，将创建新文件: {local_md_path}")
        new_content = build_markdown_content(meta, transcript, summary, actual_ai_name)
        local_md_path.parent.mkdir(parents=True, exist_ok=True)

    local_md_path.write_text(new_content, encoding='utf-8')
    logger.info("本地 Markdown 更新成功。")

    # 6. 同步到网盘
    logger.info("正在同步到网盘...")
    update_netdisk_summary(local_md_path, meta["timestamp_str"], summary, actual_ai_name)

    logger.info("全部任务执行完毕。")

if __name__ == "__main__":
    main()
