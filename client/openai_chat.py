#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenAI 聊天模块 - 提供对话和单次请求功能
"""

import sys
import time
import argparse
from pathlib import Path
from typing import List, Dict, Optional
from openai import OpenAI, OpenAIError

# 添加路径
SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))

from config import config
from ai_utils import (
    get_selected_ai_config,
    create_openai_client,
    get_single_response,
    analyze_stock_market,
    STOCK_ANALYST_SYSTEM_PROMPT,
    STOCK_ANALYST_USER_PROMPT_TEMPLATE
)

# 重新导出，保持向后兼容
__all__ = [
    'OpenAIAssistant',
    'get_single_response',
    'analyze_stock_market',
    'test_openai_api'
]

# 全局变量记录上一次请求时间
_last_request_time = 0


class OpenAIAssistant:
    """
    一个用于与OpenAI API交互的类，支持上下文记忆。
    """
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None):
        """
        初始化助手。
        :param api_key: OpenAI API Key。如果为None，将使用 config['select_open_ai'] 配置。
        :param base_url: OpenAI Base URL。如果为None，将使用配置。
        :param model: 使用的模型名称。如果为None，将使用配置。
        """
        selected_config = get_selected_ai_config()
        
        self.api_key = api_key or selected_config.get("openai_api_key")
        self.base_url = base_url or selected_config.get("openai_base_url")
        self.model = model or selected_config.get("openai_model", "gpt-3.5-turbo")
        self.interval = float(selected_config.get("interval", 0))

        if not self.api_key:
            raise ValueError("未找到 API Key。请检查 config.py 中的 select_open_ai 和 open_ai_list。")
        
        # 使用统一的客户端创建方式
        self.client = create_openai_client({
            "openai_api_key": self.api_key,
            "openai_base_url": self.base_url
        })
        
        # 初始化对话历史
        self.history: List[Dict[str, str]] = [
            {"role": "system", "content": "You are a helpful assistant."}
        ]

    def chat(self, user_input: str) -> str:
        """
        发送消息给OpenAI并获取回复（包含上下文历史）。
        :param user_input: 用户的输入文本。
        :return: 模型的回复文本。
        """
        global _last_request_time
        # 频率限制
        elapsed = time.time() - _last_request_time
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)

        self.history.append({"role": "user", "content": user_input})

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.history,
                temperature=0.7
            )
            _last_request_time = time.time()
            
            reply = response.choices[0].message.content
            self.history.append({"role": "assistant", "content": reply})
            return reply

        except OpenAIError as e:
            return f"发生错误: {str(e)}"

    def clear_history(self):
        """清空对话历史，重置为初始状态。"""
        self.history = [{"role": "system", "content": "You are a helpful assistant."}]


def test_openai_api() -> bool:
    """测试当前选中的 OpenAI API 是否可用"""
    from ai_utils import test_ai_availability, get_selected_ai_config
    ai_config = get_selected_ai_config()
    success, _ = test_ai_availability(ai_config)
    return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", type=str, help="指定BVID进行分析")
    args = parser.parse_args()

    if args.m:
        bvid = args.m
        save_text_dir = SCRIPT_DIR.parent / config.get("save_text_dir", "data/save_text")
        target_file = next((f for f in save_text_dir.glob("*.text") if bvid in f.name), None)
        
        if target_file:
            print(f"正在分析文件: {target_file.name}")
            content = target_file.read_text(encoding='utf-8')
            result = analyze_stock_market(content)
            temp_dir = SCRIPT_DIR.parent / config.get("temp_dir", "data/temp")
            temp_dir.mkdir(parents=True, exist_ok=True)
            output_file = temp_dir / f"ai_summary.txt"
            output_file.write_text(result, encoding='utf-8')
            print(f"分析结果已保存到: {output_file}")
        else:
            print(f"未找到包含 BVID {bvid} 的文件 (搜索路径: {save_text_dir})")
    else:
        r = get_single_response("你现在只能回复我发给你的消息,回复\"OK\"", "你是个回音壁")
        print(r)
