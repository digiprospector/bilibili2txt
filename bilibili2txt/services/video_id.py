from __future__ import annotations

import re
from typing import Optional


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

