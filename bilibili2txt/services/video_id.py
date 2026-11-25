from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qs, urlparse


def parse_video_input(value: str) -> tuple[Optional[str], Optional[int]]:
    value = value.strip()
    bv = re.search(r"(?i)BV([a-zA-Z0-9]{10})", value)
    if bv:
        return "BV" + bv.group(1), None
    av = re.search(r"(?i)av([0-9]+)", value)
    if av:
        return None, int(av.group(1))
    if value.isdigit():
        return None, int(value)
    if len(value) == 12 and value.lower().startswith("bv"):
        return value, None
    return None, None


def parse_video_page(value: str) -> Optional[int]:
    """从输入链接或编号中提取分P序号（如 ?p=2 或 BVxxx_p2 -> 2），未指定返回 None。"""
    raw = value.strip()
    if "://" in raw or "?" in raw or "&" in raw:
        parsed = urlparse(raw)
        p_vals = parse_qs(parsed.query).get("p")
        if p_vals:
            try:
                page = int(p_vals[0])
                if page >= 1:
                    return page
            except (TypeError, ValueError):
                pass
    match = re.search(r"(?i)(?:_p|[?&]p=)([0-9]+)\b", raw)
    if match:
        page = int(match.group(1))
        return page if page >= 1 else None
    return None

