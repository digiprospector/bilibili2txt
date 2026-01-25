#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 工具模块 - 统一管理 OpenAI 相关功能

主要功能:
- AI 配置管理 (多 API 支持)
- 请求频率限制
- 并行任务处理
- 股票分析专用功能
"""

import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from openai import OpenAI, OpenAIError, APIStatusError

# 使用统一的环境配置
from env import config


# ============== 常量定义 ==============

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

STOCK_ANALYST_SYSTEM_PROMPT = """\
你是一位有着20年A股实战经验的资深分析师和私募操盘手。
你的风格：
1. 语言专业、简练，偶尔带有老股民的干练和对市场的敬畏。
2. 深度分析：不仅看表面文字，更擅长分析背后的"政策导向"、"筹码分布"、"资金面动向"和"情绪面博弈"。
3. 逻辑清晰：习惯从'宏观环境、行业赛道、个股逻辑、风险提示'四个维度进行拆解。
4. 常用词汇：习惯使用如'放量滞涨'、'坑口复苏'、'估值修复'、'主力洗盘'、'北向资金'等内行词汇。
"""

STOCK_ANALYST_USER_PROMPT_TEMPLATE = """\
请作为资深分析师，对以下这段关于A股或相关公司的信息进行深度总结和点评。
你的任务：
1. 提取核心要点。
2. 剖析底层逻辑（为什么要关注，利好利空到底在哪里）。

待分析内容如下：
---
{content}
---
"""

# 错误关键词列表
ERROR_KEYWORDS = frozenset(["Error", "发生错误", "发生错误：", "API Key missing"])


# ============== 数据类 ==============

@dataclass
class AIConfig:
    """AI 配置数据类"""
    name: str
    api_key: str
    base_url: str
    model: str = "gpt-3.5-turbo"
    interval: float = 0.0
    is_failed: bool = False
    
    @classmethod
    def from_dict(cls, data: dict) -> "AIConfig":
        return cls(
            name=data.get("openai_api_name", "unknown"),
            api_key=data.get("openai_api_key", ""),
            base_url=data.get("openai_base_url", ""),
            model=data.get("openai_model", "gpt-3.5-turbo"),
            interval=float(data.get("interval", 0)),
            is_failed=data.get("is_failed", False),
        )
    
    def to_dict(self) -> dict:
        return {
            "openai_api_name": self.name,
            "openai_api_key": self.api_key,
            "openai_base_url": self.base_url,
            "openai_model": self.model,
            "interval": self.interval,
            "is_failed": self.is_failed,
        }


@dataclass
class RateLimiter:
    """简单的请求频率限制器"""
    _last_times: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    
    def wait_if_needed(self, key: str, interval: float) -> None:
        """如果需要，等待到满足频率限制"""
        if interval <= 0:
            return
        
        with self._lock:
            last_time = self._last_times.get(key, 0)
            elapsed = time.time() - last_time
            if elapsed < interval:
                time.sleep(interval - elapsed)
            self._last_times[key] = time.time()


# 全局频率限制器
_rate_limiter = RateLimiter()


# ============== 配置管理 ==============

class AIConfigManager:
    """AI 配置管理器"""
    
    @staticmethod
    def get_by_name(name: str) -> Optional[dict]:
        """根据名称获取 AI 配置"""
        for item in config.get("open_ai_list", []):
            if item.get("openai_api_name") == name:
                return item
        return None
    
    @staticmethod
    def get_selected() -> dict:
        """获取当前选中的 AI 配置，如果失败则返回第一个可用的"""
        select_name = config.get("select_open_ai")
        result = AIConfigManager.get_by_name(select_name)
        
        if not result or result.get("is_failed"):
            all_working = AIConfigManager.get_all()
            if all_working:
                return all_working[0]
        
        return result if result else {}
    
    @staticmethod
    def get_all(include_failed: bool = False) -> list[dict]:
        """获取所有 AI 配置"""
        configs = config.get("open_ai_list", [])
        if include_failed:
            return configs
        return [c for c in configs if not c.get("is_failed")]
    
    @staticmethod
    def mark_failed(name: str) -> None:
        """标记某个 AI 为失败"""
        for item in config.get("open_ai_list", []):
            if item.get("openai_api_name") == name:
                item["is_failed"] = True
                break
    
    @staticmethod
    def mark_available(name: str) -> None:
        """标记某个 AI 为可用"""
        for item in config.get("open_ai_list", []):
            if item.get("openai_api_name") == name:
                item["is_failed"] = False
                break


# ============== API 客户端 ==============

def create_openai_client(ai_config: dict) -> OpenAI:
    """创建 OpenAI 客户端"""
    return OpenAI(
        api_key=ai_config.get("openai_api_key"),
        base_url=ai_config.get("openai_base_url"),
        default_headers=DEFAULT_HEADERS
    )


def chat_completion(
    ai_config: dict,
    messages: list[dict],
    temperature: float = 0.7,
    timeout: int = 30
) -> str:
    """
    调用 OpenAI Chat Completion API
    
    Args:
        ai_config: AI 配置
        messages: 消息列表
        temperature: 温度参数
        timeout: 超时时间
        
    Returns:
        AI 回复内容
    """
    api_name = ai_config.get("openai_api_name", "default")
    interval = float(ai_config.get("interval", 0))
    
    # 频率限制
    _rate_limiter.wait_if_needed(api_name, interval)
    
    client = create_openai_client(ai_config)
    model = ai_config.get("openai_model", "gpt-3.5-turbo")
    
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        timeout=timeout
    )
    
    return response.choices[0].message.content


def get_single_response(
    user_prompt: str,
    system_prompt: str = "你是一个AI助手",
    ai_config: Optional[dict] = None
) -> str:
    """
    获取单次回复，不保存上下文
    
    Args:
        user_prompt: 用户输入
        system_prompt: 系统提示词
        ai_config: AI 配置 (如果为 None，使用 select_open_ai)
        
    Returns:
        AI 回复
    """
    if ai_config is None:
        ai_config = AIConfigManager.get_selected()
    
    if not ai_config.get("openai_api_key"):
        return "Error: API Key missing. 请检查 config.py 中的配置。"
    
    try:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        return chat_completion(ai_config, messages)
    except Exception as e:
        return f"Error: {e}"


# ============== AI 测试 ==============

def test_ai_availability(ai_config: dict) -> tuple[bool, str]:
    """
    测试单个 AI 配置是否可用
    
    Args:
        ai_config: AI 配置字典
        
    Returns:
        (是否成功, 消息)
    """
    name = ai_config.get("openai_api_name", "unknown")
    api_key = ai_config.get("openai_api_key")
    model = ai_config.get("openai_model", "gpt-3.5-turbo")

    if not api_key:
        return False, f"[{name}] 缺少 API Key"
    
    try:
        messages = [
            {"role": "system", "content": "你是一个回音壁"},
            {"role": "user", "content": '你现在只能回复我发给你的消息,回复"OK"'}
        ]
        reply = chat_completion(ai_config, messages, timeout=30).strip()
        
        status = "✓ 可用"
        extra = f"回复: {reply}" if "OK" not in reply.upper() else ""
        msg = f"[{name}] {status} (模型: {model}{', ' + extra if extra else ''})"
        return True, msg
            
    except APIStatusError as e:
        return False, f"[{name}] ✗ 不可用 - API错误 ({e.status_code}): {e.message}"
    except OpenAIError as e:
        return False, f"[{name}] ✗ 不可用 - OpenAI错误: {e}"
    except Exception as e:
        return False, f"[{name}] ✗ 不可用 - 错误: {e}"


def test_all_ai_apis(verbose: bool = True) -> bool:
    """
    测试所有 AI API 是否可用
    
    Args:
        verbose: 是否输出详细信息
        
    Returns:
        只要有一个可用就返回 True，失败的会被标记为 is_failed
    """
    all_configs = AIConfigManager.get_all(include_failed=True)
    
    if verbose:
        print(f"开始并行测试 {len(all_configs)} 个 AI 配置...")

    def _test_single(cfg: dict) -> tuple[dict, str, bool, str]:
        name = cfg.get("openai_api_name", "unknown")
        success, msg = test_ai_availability(cfg)
        return cfg, name, success, msg

    any_success = False
    with ThreadPoolExecutor(max_workers=len(all_configs)) as executor:
        futures = [executor.submit(_test_single, cfg) for cfg in all_configs]
        for future in as_completed(futures):
            ai_config, name, success, msg = future.result()
            if success:
                if verbose:
                    print(f"  {name}: ✓ 可用")
                any_success = True
                AIConfigManager.mark_available(name)
            else:
                if verbose:
                    print(f"  {name}: ✗ 不可用 ({msg})")
                AIConfigManager.mark_failed(name)
            
    return any_success


# ============== 业务功能 ==============

def analyze_stock_market(
    content: str,
    ai_config: Optional[dict] = None
) -> str:
    """
    使用 AI 分析股票/投资相关内容
    
    Args:
        content: 待分析的文本内容
        ai_config: AI 配置 (如果为 None，使用 select_open_ai)
        
    Returns:
        分析结果
    """
    user_prompt = STOCK_ANALYST_USER_PROMPT_TEMPLATE.format(content=content)
    return get_single_response(user_prompt, STOCK_ANALYST_SYSTEM_PROMPT, ai_config)


def is_ai_response_error(response: str) -> bool:
    """检查 AI 回复是否包含错误"""
    return any(kw in response for kw in ERROR_KEYWORDS)


def get_all_ai_summaries(
    content: str,
    system_prompt: str = STOCK_ANALYST_SYSTEM_PROMPT
) -> str:
    """
    使用所有可用的 AI API 生成总结 (并行处理)
    
    Args:
        content: 待分析的内容
        system_prompt: 系统提示词
        
    Returns:
        包含所有 AI 总结的 Markdown 字符串
    """
    ai_configs = AIConfigManager.get_all()
    if not ai_configs:
        return analyze_stock_market(content)

    def _get_single_summary(cfg: dict) -> tuple[str, str]:
        name = cfg.get("openai_api_name", "Unknown")
        try:
            summary = analyze_stock_market(content, ai_config=cfg)
            summary = summary.replace("**“", " **“")
            return name, summary
        except Exception as e:
            return name, f"Error: {e}"

    results_map = {}
    with ThreadPoolExecutor(max_workers=len(ai_configs)) as executor:
        futures = {executor.submit(_get_single_summary, cfg): cfg for cfg in ai_configs}
        for future in as_completed(futures):
            name, summary = future.result()
            results_map[name] = summary
    
    # 按配置文件顺序排列结果
    all_summaries = [
        f"### {cfg.get('openai_api_name', 'Unknown')}\n\n{results_map.get(cfg.get('openai_api_name'), 'No response')}"
        for cfg in ai_configs
    ]

    return "\n\n---\n\n".join(all_summaries)


def process_tasks_distributed(
    tasks: list[str],
    system_prompt: str = STOCK_ANALYST_SYSTEM_PROMPT,
    max_workers: Optional[int] = None
) -> list[tuple[str, str]]:
    """
    使用生产者-消费者模式，多 AI 账号并行处理不同的任务
    
    Args:
        tasks: 任务列表，每个元素是一个待处理的 content 字符串
        system_prompt: 系统提示词
        max_workers: 最大工作线程数（默认使用所有可用 AI 账号）
        
    Returns:
        结果列表，顺序与输入 tasks 一致，每个元素是 (ai_name, summary) 元组
    """
    ai_configs = AIConfigManager.get_all()
    if not ai_configs:
        # 退化为单线程循环处理
        return [("default", analyze_stock_market(content)) for content in tasks]

    num_threads = min(len(ai_configs), max_workers) if max_workers else len(ai_configs)
    task_queue: queue.Queue = queue.Queue()
    
    # 将任务放入队列
    for i, content in enumerate(tasks):
        task_queue.put((i, content))

    results: list = [None] * len(tasks)
    
    def worker(ai_config: dict) -> None:
        while True:
            try:
                index, content = task_queue.get_nowait()
            except queue.Empty:
                break
            
            try:
                summary = analyze_stock_market(content, ai_config=ai_config)
                summary = summary.replace("**“", " **“")
                name = ai_config.get("openai_api_name", "AI")
                results[index] = (name, summary)
            except Exception as e:
                results[index] = ("Error", str(e))
            finally:
                task_queue.task_done()

    threads = [
        threading.Thread(target=worker, args=(ai_configs[i],))
        for i in range(num_threads)
    ]
    
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    return results


# ============== 流式任务处理器 ==============

class BatchTaskProcessor:
    """
    生产者-消费者模式处理器
    支持边扫描边加入任务（Streaming mode）
    """
    
    def __init__(
        self, 
        system_prompt: str = STOCK_ANALYST_SYSTEM_PROMPT, 
        max_workers: Optional[int] = None,
        on_result_callback: Optional[Callable[[Any, str, str, Any], None]] = None
    ):
        """
        初始化处理器
        
        Args:
            system_prompt: 系统提示词
            max_workers: 最大工作线程数
            on_result_callback: 结果回调函数 (task_id, ai_name, summary, extra_info)
        """
        self.system_prompt = system_prompt
        self.on_result_callback = on_result_callback
        self.task_queue: queue.Queue = queue.Queue()
        self.ai_configs = AIConfigManager.get_all()
        
        self.num_threads = 1
        if self.ai_configs:
            self.num_threads = min(len(self.ai_configs), max_workers) if max_workers else len(self.ai_configs)
            
        self.threads: list[threading.Thread] = []
        self.stop_event = threading.Event()
        self._start_workers()

    def _start_workers(self) -> None:
        """启动工作线程"""
        for i in range(self.num_threads):
            cfg = self.ai_configs[i] if self.ai_configs else None
            t = threading.Thread(target=self._worker_loop, args=(cfg,), daemon=True)
            t.start()
            self.threads.append(t)

    def _worker_loop(self, ai_config: Optional[dict]) -> None:
        """工作线程循环"""
        ai_name = ai_config.get("openai_api_name", "AI") if ai_config else "DefaultAI"
        
        while not self.stop_event.is_set() or not self.task_queue.empty():
            try:
                task = self.task_queue.get(timeout=1)
                task_id, content, extra_info = task
            except queue.Empty:
                continue
            
            try:
                summary = analyze_stock_market(content, ai_config=ai_config)
                summary = summary.replace("**“", " **“")
                
                if is_ai_response_error(summary):
                    raise RuntimeError(f"AI Response contains error: {summary}")

                if self.on_result_callback:
                    self.on_result_callback(task_id, ai_name, summary, extra_info)
                
                self.task_queue.task_done()
                
            except Exception as e:
                print(f"[⚠️ AI 退休] 账号 [{ai_name}] 发生错误，任务将回滚到队列。错误: {e}")
                self.task_queue.put(task)
                self.task_queue.task_done()
                break  # 线程退出

    def add_task(self, task_id: Any, content: str, extra_info: Any = None) -> None:
        """向队列添加任务"""
        self.task_queue.put((task_id, content, extra_info))

    def wait_and_stop(self) -> None:
        """等待所有已添加任务处理完并停止线程"""
        self.task_queue.join()
        self.stop_event.set()
        for t in self.threads:
            t.join()


# ============== 兼容性别名 ==============
# 保持向后兼容

def get_ai_config_by_name(name: str) -> Optional[dict]:
    """根据名称获取 AI 配置 (兼容性别名)"""
    return AIConfigManager.get_by_name(name)

def get_selected_ai_config() -> dict:
    """获取当前选中的 AI 配置 (兼容性别名)"""
    return AIConfigManager.get_selected()

def get_all_ai_configs(include_failed: bool = False) -> list[dict]:
    """获取所有 AI 配置 (兼容性别名)"""
    return AIConfigManager.get_all(include_failed)

def mark_ai_as_failed(name: str) -> None:
    """标记某个 AI 为失败 (兼容性别名)"""
    AIConfigManager.mark_failed(name)
