#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
from pathlib import Path
from typing import List, Dict, Optional
from openai import OpenAI, OpenAIError

SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))
from config import config

class OpenAIAssistant:
    """
    一个用于与OpenAI API交互的类，支持上下文记忆。
    """
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None):
        """
        初始化助手。
        :param api_key: OpenAI API Key。如果为None，将尝试从 config.py 获取。
        :param base_url: OpenAI Base URL。如果为None，将尝试从 config.py 获取。
        :param model: 使用的模型名称。如果为None，将尝试从 config.py 获取，默认为 gpt-3.5-turbo。
        """
        self.api_key = api_key or config.get("openai_api_key")
        self.base_url = base_url or config.get("openai_base_url")

        if not self.api_key:
            raise ValueError("未找到 API Key。请传入 api_key 参数或在 config.py 中设置 openai_api_key。")
        
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        self.model = model or config.get("openai_model", "gpt-3.5-turbo")
        # 初始化对话历史，可以根据需要添加系统提示词(System Prompt)
        self.history: List[Dict[str, str]] = [
            {"role": "system", "content": "You are a helpful assistant."}
        ]

    def chat(self, user_input: str) -> str:
        """
        发送消息给OpenAI并获取回复（包含上下文历史）。
        :param user_input: 用户的输入文本。
        :return: 模型的回复文本。
        """
        self.history.append({"role": "user", "content": user_input})

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.history,
                temperature=0.7
            )
            
            print(response)
            reply = response.choices[0].message.content
            self.history.append({"role": "assistant", "content": reply})
            return reply

        except OpenAIError as e:
            return f"发生错误: {str(e)}"

    def clear_history(self):
        """清空对话历史，重置为初始状态。"""
        self.history = [{"role": "system", "content": "You are a helpful assistant."}]


def get_single_response(user_prompt: str, system_role_definition: str="你是一个AI助手", api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None) -> str:
    """
    一个独立的函数，用于获取单次回复，不保存上下文。
    适合其他程序简单调用。
    """
    try:
        # 如果没有传入key，尝试从config获取
        key = api_key or config.get("openai_api_key")
        base = base_url or config.get("openai_base_url")
        use_model = model or config.get("openai_model", "gpt-3.5-turbo")
        
        if not key:
            return "Error: API Key missing."

        client = OpenAI(api_key=key, base_url=base)
        response = client.chat.completions.create(
            model=use_model,
            messages=[
                {"role": "system", "content": system_role_definition},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error: {str(e)}"

def analyze_stock_market(text_content, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None) -> str:
    """
    让资深A股分析师分析总结内容
    """
    
    # 核心：设定 System Prompt
    system_role_definition = """
    你是一位有着20年A股实战经验的资深分析师和私募操盘手。
    你的风格：
    1. 语言专业、简练，偶尔带有老股民的干练和对市场的敬畏。
    2. 深度分析：不仅看表面文字，更擅长分析背后的“政策导向”、“筹码分布”、“资金面动向”和“情绪面博弈”。
    3. 逻辑清晰：习惯从‘宏观环境、行业赛道、个股逻辑、风险提示’四个维度进行拆解。
    4. 常用词汇：习惯使用如‘放量滞涨’、‘坑口复苏’、‘估值修复’、‘主力洗盘’、‘北向资金’等内行词汇。
    """
    user_prompt = f"""
    请作为资深分析师，对以下这段关于A股或相关公司的信息进行深度总结和点评。
    你的任务：
    1. 提取核心要点。
    2. 剖析底层逻辑（为什么要关注，利好利空到底在哪里）。
    3. 给出你的‘老民股操作建议’（风险自担）。
    
    待分析内容如下：
    ---
    {text_content}
    ---
    """
    try:
        return get_single_response(system_role_definition, user_prompt, api_key, base_url, model)
    except Exception as e:
        return f"发生错误：{e}"
    
def test_openai_api():
    r = get_single_response("你现在只能回复我发给你的消息,回复\"OK\"")
    if r == "OK":
        return True
    else:
        return False

if __name__ == "__main__":
        # 检查配置
    if not config.get("openai_api_key"):
        print("警告: config.py 中未检测到 openai_api_key。")
        key_input = input("请输入你的 OpenAI API Key: ").strip()
        if key_input:
            config["openai_api_key"] = key_input
        else:
            print("无法继续，程序退出。")
            sys.exit(1)

    r = get_single_response("你现在只能回复我发给你的消息,回复\"OK\"", "你是个回音壁")

    print(r)
