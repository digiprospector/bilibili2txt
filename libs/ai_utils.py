#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 工具模块 - 统一管理 OpenAI 相关功能
"""

import time
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
import sys

# 添加 common 目录到 path
SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))
from config import config

from openai import OpenAI, OpenAIError, APIStatusError
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============== 常量定义 ==============

# 默认请求头 (防止被 Cloudflare 等拦截)
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# 股票分析师 System Prompt
STOCK_ANALYST_SYSTEM_PROMPT = """
你是一位有着20年A股实战经验的资深分析师和私募操盘手。
你的风格：
1. 语言专业、简练，偶尔带有老股民的干练和对市场的敬畏。
2. 深度分析：不仅看表面文字，更擅长分析背后的"政策导向"、"筹码分布"、"资金面动向"和"情绪面博弈"。
3. 逻辑清晰：习惯从'宏观环境、行业赛道、个股逻辑、风险提示'四个维度进行拆解。
4. 常用词汇：习惯使用如'放量滞涨'、'坑口复苏'、'估值修复'、'主力洗盘'、'北向资金'等内行词汇。
"""

# 股票分析师 User Prompt 模板
STOCK_ANALYST_USER_PROMPT_TEMPLATE = """
请作为资深分析师，对以下这段关于A股或相关公司的信息进行深度总结和点评。
你的任务：
1. 提取核心要点。
2. 剖析底层逻辑（为什么要关注，利好利空到底在哪里）。

待分析内容如下：
---
{content}
---
"""

# 全局变量记录上一次请求时间 (用于频率限制，键为 api_name)
_last_request_times = {}


# ============== 配置获取 ==============

def get_ai_config_by_name(name: str) -> Optional[Dict[str, Any]]:
    """根据名称获取 AI 配置"""
    for item in config.get("open_ai_list", []):
        if item.get("openai_api_name") == name:
            return item
    return None


def get_selected_ai_config() -> Dict[str, Any]:
    """根据 config['select_open_ai'] 获取当前选中的 AI 配置"""
    select_name = config.get("select_open_ai")
    result = get_ai_config_by_name(select_name)
    return result if result else {}


def get_all_ai_configs() -> list:
    """获取所有 AI 配置"""
    return config.get("open_ai_list", [])


# ============== 客户端创建 ==============

def create_openai_client(ai_config: Dict[str, Any]) -> OpenAI:
    """
    创建 OpenAI 客户端 (带默认请求头)
    :param ai_config: AI 配置字典
    :return: OpenAI 客户端实例
    """
    return OpenAI(
        api_key=ai_config.get("openai_api_key"),
        base_url=ai_config.get("openai_base_url"),
        default_headers=DEFAULT_HEADERS
    )


# ============== API 调用 ==============

def chat_completion(
    ai_config: Dict[str, Any],
    messages: list,
    temperature: float = 0.7,
    timeout: int = 30
) -> str:
    """
    调用 OpenAI Chat Completion API
    :param ai_config: AI 配置
    :param messages: 消息列表
    :param temperature: 温度参数
    :param timeout: 超时时间
    :return: 回复内容
    """
    global _last_request_times
    
    api_name = ai_config.get("openai_api_name", "default")
    
    # 频率限制
    interval = float(ai_config.get("interval", 0))
    last_time = _last_request_times.get(api_name, 0)
    elapsed = time.time() - last_time
    if elapsed < interval:
        time.sleep(interval - elapsed)
    
    client = create_openai_client(ai_config)
    model = ai_config.get("openai_model", "gpt-3.5-turbo")
    
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        timeout=timeout
    )
    
    _last_request_times[api_name] = time.time()
    return response.choices[0].message.content


def get_single_response(
    user_prompt: str,
    system_prompt: str = "你是一个AI助手",
    ai_config: Optional[Dict[str, Any]] = None
) -> str:
    """
    获取单次回复，不保存上下文
    :param user_prompt: 用户输入
    :param system_prompt: 系统提示词
    :param ai_config: AI 配置 (如果为 None，使用 select_open_ai)
    :return: AI 回复
    """
    if ai_config is None:
        ai_config = get_selected_ai_config()
    
    if not ai_config.get("openai_api_key"):
        return "Error: API Key missing. 请检查 config.py 中的配置。"
    
    try:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        return chat_completion(ai_config, messages)
    except Exception as e:
        return f"Error: {str(e)}"


# ============== AI 测试 ==============

def test_ai_availability(ai_config: Dict[str, Any]) -> Tuple[bool, str]:
    """
    测试单个 AI 配置是否可用
    :param ai_config: AI 配置字典
    :return: (是否成功, 消息)
    """
    name = ai_config.get("openai_api_name", "unknown")
    api_key = ai_config.get("openai_api_key")
    model = ai_config.get("openai_model", "gpt-3.5-turbo")

    if not api_key:
        return False, f"[{name}] 缺少 API Key"
    
    try:
        messages = [
            {"role": "system", "content": "你是一个回音壁"},
            {"role": "user", "content": "你现在只能回复我发给你的消息,回复\"OK\""}
        ]
        reply = chat_completion(ai_config, messages, timeout=30)
        reply = reply.strip()
        
        if "OK" in reply.upper():
            return True, f"[{name}] ✓ 可用 (模型: {model})"
        else:
            return True, f"[{name}] ✓ 可用 (模型: {model}, 回复: {reply})"
            
    except APIStatusError as e:
        print(f"Status Code: {e.status_code}")
        print(f"Response: {e.response.text}")
        return False, f"[{name}] ✗ 不可用 - API错误: {str(e)}"
    except OpenAIError as e:
        return False, f"[{name}] ✗ 不可用 - OpenAI错误: {str(e)}"
    except Exception as e:
        return False, f"[{name}] ✗ 不可用 - 错误: {str(e)}"


# ============== 业务功能 ==============

def analyze_stock_market(
    content: str,
    ai_config: Optional[Dict[str, Any]] = None
) -> str:
    """
    使用 AI 分析股票/投资相关内容
    :param content: 待分析的文本内容
    :param ai_config: AI 配置 (如果为 None，使用 select_open_ai)
    :return: 分析结果
    """
    user_prompt = STOCK_ANALYST_USER_PROMPT_TEMPLATE.format(content=content)
    return get_single_response(user_prompt, STOCK_ANALYST_SYSTEM_PROMPT, ai_config)


def is_ai_response_error(response: str) -> bool:
    """检查 AI 回复是否包含错误"""
    error_keywords = ["Error", "发生错误", "发生错误：", "API Key missing"]
    for kw in error_keywords:
        if kw in response:
            return True
    return False


def get_all_ai_summaries(
    content: str,
    system_prompt: str = STOCK_ANALYST_SYSTEM_PROMPT
) -> str:
    """
    使用所有可用的 AI API 生成总结 (并行处理)
    :param content: 待分析的内容
    :param system_prompt: 系统提示词
    :return: 包含所有 AI 总结的 Markdown 字符串
    """
    ai_configs = get_all_ai_configs()
    if not ai_configs:
        return analyze_stock_market(content) # 退回到默认行为

    def _get_single_summary(cfg):
        name = cfg.get("openai_api_name", "Unknown")
        try:
            summary = analyze_stock_market(content, ai_config=cfg)
            summary = summary.replace("**“", " **“")
            return name, summary
        except Exception as e:
            return name, f"Error: {str(e)}"

    results_map = {}
    with ThreadPoolExecutor(max_workers=len(ai_configs)) as executor:
        future_to_config = {executor.submit(_get_single_summary, cfg): cfg for cfg in ai_configs}
        for future in as_completed(future_to_config):
            name, summary = future.result()
            results_map[name] = summary
    
    # 按照配置文件的顺序排列结果
    all_summaries = []
    for cfg in ai_configs:
        name = cfg.get("openai_api_name", "Unknown")
        summary = results_map.get(name, "No response")
        all_summaries.append(f"### {name}\n\n{summary}")

    return "\n\n---\n\n".join(all_summaries)
