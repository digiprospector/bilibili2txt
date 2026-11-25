from __future__ import annotations

import logging
from typing import Any

from openai import OpenAI, APIError, APITimeoutError, APIConnectionError

from ..config import AppConfig
from .prompts import (
    DEFAULT_INVESTMENT_SYSTEM_PROMPT,
    DEFAULT_INVESTMENT_USER_PROMPT_TEMPLATE,
    PromptConfig,
    get_prompt_for_category,
)


DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def format_api_error(exc: Exception) -> str:
    if isinstance(exc, APITimeoutError):
        return "网络请求超时，请检查您的网络连接或代理设置。"
    elif isinstance(exc, APIConnectionError):
        return f"网络连接失败，请检查您的代理或网络设置。错误详情: {exc}"
    elif isinstance(exc, APIError):
        status_code = getattr(exc, "status_code", None)
        body = getattr(exc, "body", None)
        message = None
        code = None
        err_type = None
        if isinstance(body, dict) and "error" in body:
            err = body["error"]
            if isinstance(err, dict):
                message = err.get("message")
                code = err.get("code")
                err_type = err.get("type")
        if not message:
            message = getattr(exc, "message", None) or str(exc)
        if not code:
            code = getattr(exc, "code", None)
        if not err_type:
            err_type = getattr(exc, "type", None)

        parts = []
        if status_code is not None:
            parts.append(f"HTTP {status_code}")
        if code:
            parts.append(f"Code: {code}")
        if err_type:
            parts.append(f"Type: {err_type}")
        if message:
            parts.append(f"Message: {message}")

        return " | ".join(parts) if parts else str(exc)
    return str(exc)



STOCK_ANALYST_SYSTEM_PROMPT = DEFAULT_INVESTMENT_SYSTEM_PROMPT
STOCK_ANALYST_USER_PROMPT_TEMPLATE = DEFAULT_INVESTMENT_USER_PROMPT_TEMPLATE


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
        category: str | None = None,
        prompt_config: PromptConfig | None = None,
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

        client = OpenAI(
            api_key=api_key,
            base_url=provider.get("base_url"),
            default_headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        model_name = model or provider.get("model", "gpt-4o-mini")
        prompts_dir = self.config.prompts_dir
        prompt_cfg = prompt_config or get_prompt_for_category(category or "投资", prompts_dir, self.logger)
        system_prompt = prompt_config.system_prompt if prompt_config else (provider.get("prompt") or prompt_cfg.system_prompt)
        user_content = prompt_cfg.user_prompt_template.format(content=content)
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
            client = OpenAI(
                api_key=api_key,
                base_url=provider.get("base_url"),
                default_headers={"User-Agent": DEFAULT_USER_AGENT},
            )
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
            return False, f"[{name}] {format_api_error(exc)}"

    def _resolve_secret(self, provider: dict[str, Any], key: str) -> str | None:
        env_key = provider.get(f"{key}_env")
        if env_key:
            import os

            return os.environ.get(env_key)
        value = provider.get(key)
        return str(value) if value else None
