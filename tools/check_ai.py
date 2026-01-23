#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查 config 里面 open_ai_list 配置的 AI 是否可用
用法:
    python check_ai.py          # 检查所有 AI
    python check_ai.py -n bohe  # 只检查名为 bohe 的 AI
"""

import sys
import argparse
from pathlib import Path
from typing import List

# 添加 libs 目录到 path
SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))

from ai_utils import (
    get_ai_config_by_name,
    get_all_ai_configs,
    test_ai_availability,
    test_all_ai_apis,
    mark_ai_as_failed
)


def check_all_ai() -> bool:
    """检查所有 AI 配置并返回是否至少有一个可用"""
    return test_all_ai_apis(verbose=True)


def check_single_ai(name: str) -> tuple[bool, str]:
    """检查指定名称的 AI 配置"""
    ai_config = get_ai_config_by_name(name)
    
    if not ai_config:
        return False, f"未找到名为 '{name}' 的 AI 配置"
    
    print(f"正在测试: {name} ...", end=" ", flush=True)
    success, message = test_ai_availability(ai_config)
    print("完成")
    
    return success, message


def main():
    parser = argparse.ArgumentParser(description="检查 config 里面 open_ai_list 配置的 AI 是否可用")
    parser.add_argument("-n", "--name", type=str, help="指定要测试的 AI 名称 (openai_api_name)")
    parser.add_argument("-l", "--list", action="store_true", help="列出所有可用的 AI 配置名称")
    
    args = parser.parse_args()
    
    # 列出所有 AI 名称
    if args.list:
        ai_list = get_all_ai_configs()
        print("可用的 AI 配置:")
        for ai in ai_list:
            name = ai.get("openai_api_name", "unknown")
            model = ai.get("openai_model", "unknown")
            base_url = ai.get("openai_base_url", "unknown")
            print(f"  - {name} (模型: {model}, URL: {base_url})")
        return
    
    # 检查指定的 AI
    if args.name:
        success, message = check_single_ai(args.name)
        print(f"\n{message}")
        sys.exit(0 if success else 1)
    
    # 检查所有 AI
    success = check_all_ai()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
