from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


@dataclass
class SyncStats:
    copied: int = 0
    skipped: int = 0
    conflicts: int = 0
    archived: int = 0


class NetdiskSync:
    def __init__(self, markdown_root: Path, netdisk_root: Path, logger: logging.Logger):
        self.markdown_root = markdown_root
        self.dest_root = netdisk_root / "markdown"
        self.logger = logger

    def sync(self, force: bool = False, today: date | None = None) -> SyncStats:
        today = today or date.today()
        stats = SyncStats()
        if today.day == 1:
            stats.archived += self.archive_previous_month(today, force)

        if not self.markdown_root.exists():
            raise RuntimeError(f"Markdown source does not exist: {self.markdown_root}")
        if not self.dest_root.parent.exists():
            raise RuntimeError(f"Netdisk root does not exist: {self.dest_root.parent}")

        for day_dir in sorted(path for path in self.markdown_root.iterdir() if path.is_dir()):
            try:
                file_date = date.fromisoformat(day_dir.name)
            except ValueError:
                self.logger.info("跳过非日期格式的 markdown 目录：%s", day_dir)
                continue
            for md_file in day_dir.glob("*.md"):
                dest = self.destination_for(file_date, md_file.name, today)
                self._copy(md_file, dest, force, stats)
        return stats

    def archive_previous_month(self, today: date, force: bool) -> int:
        first_this_month = today.replace(day=1)
        last_month_day = first_this_month - timedelta(days=1)
        compact = self.dest_root / f"{last_month_day.year}-{last_month_day.month:02d}"
        if not compact.exists():
            self.logger.info("没有上个月的紧凑目录需要归档：%s", compact)
            return 0
        archived = 0
        for day_dir in sorted(path for path in compact.iterdir() if path.is_dir()):
            target_day = self.dest_root / f"{last_month_day.year}" / f"{last_month_day.month:02d}" / day_dir.name
            for source in day_dir.glob("*.md"):
                target = target_day / source.name
                self._move(source, target, force)
                archived += 1
        self._remove_empty_dirs(compact)
        return archived

    def destination_for(self, file_date: date, filename: str, today: date) -> Path:
        clean_name = _strip_timestamp(filename)
        if file_date.year == today.year and file_date.month == today.month:
            return self.dest_root / f"{file_date.year}-{file_date.month:02d}" / f"{file_date.day:02d}" / clean_name
        return self.dest_root / f"{file_date.year}" / f"{file_date.month:02d}" / f"{file_date.day:02d}" / clean_name

    def _copy(self, source: Path, target: Path, force: bool, stats: SyncStats) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not force:
            self.logger.debug("跳过已存在的网盘文件：%s", target)
            stats.skipped += 1
            return
        shutil.copy2(source, target)
        self.logger.info("已同步 Markdown：%s -> %s", source, target)
        stats.copied += 1

    def _move(self, source: Path, target: Path, force: bool) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if source.read_bytes() == target.read_bytes():
                source.unlink()
                self.logger.info("已删除重复的归档源文件：%s", source)
                return
            if not force:
                self.logger.warning("归档冲突，保留目标文件：%s", target)
                return
            target.unlink()
        shutil.move(str(source), str(target))
        self.logger.info("已归档上个月文件：%s -> %s", source, target)

    def _remove_empty_dirs(self, root: Path) -> None:
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        if root.exists() and root.is_dir() and not any(root.iterdir()):
            root.rmdir()


def _strip_timestamp(filename: str) -> str:
    if filename.startswith("["):
        end = filename.find("]")
        if end != -1:
            return filename[end + 1 :]
    return filename

