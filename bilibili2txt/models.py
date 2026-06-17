from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class Task:
    task_id: str
    bvid: str
    title: str
    up_name: str
    up_mid: int | None
    pubdate: int | None
    duration: int
    cid: int | None
    status: str
    source_url: str
    created_at: str
    aid: int | None = None
    attempts: int = 0
    max_attempts: int = 3
    claimed_by: str | None = None
    claimed_at: str | None = None
    last_error: str | None = None
    failed_at: str | None = None
    failed_by: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        return cls(
            task_id=str(data.get("task_id") or data["bvid"]),
            bvid=str(data["bvid"]),
            title=str(data.get("title", "")),
            up_name=str(data.get("up_name", "")),
            up_mid=_optional_int(data.get("up_mid")),
            pubdate=_optional_int(data.get("pubdate")),
            duration=int(data.get("duration") or 0),
            cid=_optional_int(data.get("cid")),
            status=str(data.get("status", "normal")),
            source_url=str(data.get("source_url") or f"https://www.bilibili.com/video/{data['bvid']}"),
            created_at=str(data.get("created_at") or now_iso()),
            aid=_optional_int(data.get("aid")),
            attempts=int(data.get("attempts") or 0),
            max_attempts=int(data.get("max_attempts") or 3),
            claimed_by=data.get("claimed_by"),
            claimed_at=data.get("claimed_at"),
            last_error=data.get("last_error"),
            failed_at=data.get("failed_at"),
            failed_by=data.get("failed_by"),
        )

    @classmethod
    def from_bilibili_info(cls, info: dict[str, Any]) -> "Task":
        bvid = str(info["bvid"])
        return cls(
            task_id=bvid,
            bvid=bvid,
            title=str(info.get("title", "")),
            up_name=str(info.get("up_name", "")),
            up_mid=info.get("up_mid"),
            pubdate=info.get("pubdate"),
            duration=int(info.get("duration") or 0),
            cid=info.get("cid"),
            status=str(info.get("status") or "normal"),
            source_url=str(info.get("source_url") or f"https://www.bilibili.com/video/{bvid}"),
            created_at=now_iso(),
            aid=info.get("aid"),
        )

    @classmethod
    def from_file(cls, path: Path) -> "Task":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @property
    def filename(self) -> str:
        safe_created = (
            self.created_at.replace(":", "")
            .replace("-", "")
            .replace("+", "")
            .replace(".", "")
        )
        safe_created = safe_created.split("T", 1)[0] + "T" + safe_created.split("T", 1)[1][:6] if "T" in safe_created else safe_created
        return f"{self.duration:06d}_{safe_created}_{self.bvid}.json"

    def mark_claimed(self, server_id: str) -> None:
        self.attempts += 1
        self.claimed_by = server_id
        self.claimed_at = now_iso()
        self.last_error = None

    def clear_claim(self) -> None:
        self.claimed_by = None
        self.claimed_at = None

    def reset_for_resubmit(self) -> None:
        self.attempts = 0
        self.claimed_by = None
        self.claimed_at = None
        self.last_error = None
        self.status = "normal"

    def mark_failed(self, error: str, server_id: str | None = None) -> None:
        self.last_error = error
        self.failed_at = now_iso()
        self.failed_by = server_id


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)

