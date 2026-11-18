from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..paths import ROOT_DIR


@dataclass
class PromptConfig:
    name: str
    description: str
    system_prompt: str
    user_prompt_template: str


# ---------------------------------------------------------------------------
# 内置默认 Prompt 配置
# ---------------------------------------------------------------------------

DEFAULT_INVESTMENT_SYSTEM_PROMPT = """\
你是一位有着20年A股实战经验的资深分析师和私募操盘手。
你的风格：
1. 语言专业、简练，偶尔带有老股民的干练和对市场的敬畏。
2. 深度分析：不仅看表面文字，更擅长分析背后的"政策导向"、"筹码分布"、"资金面动向"和"情绪面博弈"。
3. 逻辑清晰：习惯从'宏观环境、行业赛道、个股逻辑、风险提示'四个维度进行拆解。
4. 常用词汇：习惯使用如'放量滞涨'、'坑口复苏'、'估值修复'、'主力洗盘'、'北向资金'等内行词汇。
"""

DEFAULT_INVESTMENT_USER_PROMPT_TEMPLATE = """\
请作为资深分析师，对以下这段关于A股或相关公司的信息进行深度总结和点评。
你的任务：
1. 提取核心要点。
2. 剖析底层逻辑（为什么要关注，利好利空到底在哪里）。

待分析内容如下：
---
{content}
---
"""

DEFAULT_HISTORY_SYSTEM_PROMPT = """\
你是一位治学严谨、见解深刻的历史学者与人文观察家。
你的风格：
1. 语言沉稳、客观、凝练，擅长透过历史表象剖析底层深层规律与人性博弈。
2. 宏观与微观兼顾：既能从时代大局、地缘政治、制度经济等宏观视角把握大势，又能从关键人物性格、决策心理等微观细节复盘关键历史转折。
3. 逻辑清晰、结构分明：
   - 【时代背景与大局】：厘清事件爆发前夕的历史背景、时代局限与关键前提。
   - 【核心人物与转折】：梳理关键人物、重大抉择与关键时间节点的历史转折。
   - 【深层成因与博弈】：剖析背后的政治权力、经济利益、社会阶层与地缘格局等多重博弈。
   - 【历史影响与启示】：总结该事件对历史走向的深远影响，以及带给当下的思考与现实启示。
"""

DEFAULT_HISTORY_USER_PROMPT_TEMPLATE = """\
请作为资深历史学者，对以下历史相关的内容进行系统、深度的梳理与总结。
你的任务：
1. 梳理历史脉络与关键事实。
2. 剖析深层成因与博弈逻辑。
3. 提炼历史深远影响与现实启示。

待分析内容如下：
---
{content}
---
"""

BUILTIN_PROMPTS: dict[str, PromptConfig] = {
    "投资": PromptConfig(
        name="投资",
        description="A股实战、宏观经济、行业赛道与上市公司深度分析",
        system_prompt=DEFAULT_INVESTMENT_SYSTEM_PROMPT,
        user_prompt_template=DEFAULT_INVESTMENT_USER_PROMPT_TEMPLATE,
    ),
    "历史": PromptConfig(
        name="历史",
        description="历史脉络、时代背景、关键人物博弈与深远启示总结",
        system_prompt=DEFAULT_HISTORY_SYSTEM_PROMPT,
        user_prompt_template=DEFAULT_HISTORY_USER_PROMPT_TEMPLATE,
    ),
}


def load_prompts_from_dir(prompts_dir: Path | None, logger: logging.Logger | None = None) -> dict[str, PromptConfig]:
    """从指定目录动态加载自定义 YAML 提示词配置"""
DEFAULT_PROMPTS_DIR = ROOT_DIR / "prompts"


def load_prompts_from_dir(prompts_dir: Path | None = None, logger: logging.Logger | None = None) -> dict[str, PromptConfig]:
    """从指定目录动态加载 YAML 提示词配置（默认为仓库根目录 prompts）"""
    configs = dict(BUILTIN_PROMPTS)
    if not prompts_dir or not prompts_dir.exists():
        prompts_dir = prompts_dir or DEFAULT_PROMPTS_DIR
    if not prompts_dir.exists():
        return configs

    for file_path in prompts_dir.glob("*.yaml"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                continue
            name = str(data.get("name") or file_path.stem).strip()
            desc = str(data.get("description") or "").strip()
            sys_prompt = str(data.get("system_prompt") or "").strip()
            user_prompt = str(data.get("user_prompt_template") or "").strip()

            if name and sys_prompt and user_prompt:
                configs[name] = PromptConfig(
                    name=name,
                    description=desc,
                    system_prompt=sys_prompt,
                    user_prompt_template=user_prompt,
                )
        except Exception as exc:
            if logger:
                logger.warning("加载提示词配置文件失败 %s: %s", file_path, exc)

    return configs


def get_available_categories(prompts_dir: Path | None = None, logger: logging.Logger | None = None) -> list[PromptConfig]:
    """获取所有可用的分类列表"""
    prompts = load_prompts_from_dir(prompts_dir, logger)
    return list(prompts.values())


def get_category_names(prompts_dir: Path | None = None, logger: logging.Logger | None = None) -> list[str]:
    """获取所有可用分类的名称列表"""
    return [c.name for c in get_available_categories(prompts_dir, logger)]


def get_prompt_for_category(
    category: str,
    prompts_dir: Path | None = None,
    logger: logging.Logger | None = None,
) -> PromptConfig:
    """获取指定分类的 Prompt 配置，若未找到则默认回退到 '投资'"""
    prompts = load_prompts_from_dir(prompts_dir, logger)
    if category in prompts:
        return prompts[category]
    if "投资" in prompts:
        return prompts["投资"]
    return next(iter(prompts.values()))
