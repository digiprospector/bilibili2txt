from __future__ import annotations

import logging
from typing import Any

from openai import OpenAI

from ..config import AppConfig


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


class AIService:
    def __init__(self, config: AppConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self._working_providers = None

    def providers(self) -> list[dict[str, Any]]:
        if self._working_providers is not None:
            return self._working_providers
        ai = self.config.get("ai", {}) or {}
        raw = list(ai.get("providers", []) or [])
        return [p for p in raw if p.get("enable", True) is not False]

    def test_and_filter_providers(self) -> None:
        self.logger.info("正在测试所有配置的 AI 供应商...")
        working = []
        for provider in self.providers():
            passed, msg = self.test_provider(provider)
            if passed:
                working.append(provider)
                self.logger.info("AI 供应商 [%s] 测试成功", provider.get("name"))
            else:
                self.logger.warning("AI 供应商 [%s] 测试失败且已被禁用：%s", provider.get("name"), msg)
        self._working_providers = working

    def selected_provider(self) -> dict[str, Any] | None:
        selected = self.config.get("ai.selected")
        for provider in self.providers():
            if provider.get("name") == selected:
                return provider
        return self.providers()[0] if self.providers() else None

    def summarize(
        self,
        content: str,
        provider_name: str | None = None,
        model: str | None = None,
    ) -> tuple[str, str]:
        if provider_name:
            provider = None
            for p in self.providers():
                if p.get("name") == provider_name:
                    provider = p
                    break
            if not provider:
                raise RuntimeError(f"AI provider {provider_name} not found")
        else:
            provider = self.selected_provider()

        if not provider:
            raise RuntimeError("No AI providers configured")

        api_key = self._resolve_secret(provider, "api_key")
        if not api_key:
            raise RuntimeError(f"Missing API key for provider {provider.get('name')}")

        client = OpenAI(api_key=api_key, base_url=provider.get("base_url"))
        model_name = model or provider.get("model", "gpt-4o-mini")
        system_prompt = provider.get("prompt") or STOCK_ANALYST_SYSTEM_PROMPT
        user_content = STOCK_ANALYST_USER_PROMPT_TEMPLATE.format(content=content)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            timeout=300,
        )
        text = response.choices[0].message.content or ""
        return provider.get("name", "unknown"), text

    def test_provider(self, provider: dict[str, Any]) -> tuple[bool, str]:
        api_key = self._resolve_secret(provider, "api_key")
        name = provider.get("name", "unknown")
        if not api_key:
            return False, f"[{name}] missing API key"
        try:
            client = OpenAI(api_key=api_key, base_url=provider.get("base_url"))
            response = client.chat.completions.create(
                model=provider.get("model", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": "你是一个回音壁"},
                    {"role": "user", "content": '你现在只能回复"OK"'},
                ],
                timeout=60,
            )
            reply = (response.choices[0].message.content or "").strip()
            return "OK" in reply.upper(), f"[{name}] reply={reply}"
        except Exception as exc:
            return False, f"[{name}] {exc}"

    def _resolve_secret(self, provider: dict[str, Any], key: str) -> str | None:
        env_key = provider.get(f"{key}_env")
        if env_key:
            import os

            return os.environ.get(env_key)
        value = provider.get(key)
        return str(value) if value else None
