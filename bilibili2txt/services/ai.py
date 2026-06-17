from __future__ import annotations

import logging
from typing import Any

from openai import OpenAI

from ..config import AppConfig


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

    def summarize(self, content: str) -> tuple[str, str]:
        provider = self.selected_provider()
        if not provider:
            raise RuntimeError("No AI providers configured")

        api_key = self._resolve_secret(provider, "api_key")
        if not api_key:
            raise RuntimeError(f"Missing API key for provider {provider.get('name')}")

        client = OpenAI(api_key=api_key, base_url=provider.get("base_url"))
        model = provider.get("model", "gpt-4o-mini")
        prompt = provider.get("prompt") or "请总结以下内容，并输出 Markdown。"
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": content},
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
