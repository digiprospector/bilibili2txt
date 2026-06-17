from datetime import date
from pathlib import Path
import logging

from bilibili2txt.services.netdisk import NetdiskSync


def test_sync_current_month_to_compact_dir(tmp_path: Path):
    source = tmp_path / "data" / "markdown"
    source_day = source / "2026-06-16"
    source_day.mkdir(parents=True)
    (source_day / "[2026-06-16_10-00-00][UP][Title][BVxxx].md").write_text("x", encoding="utf-8")

    netdisk = tmp_path / "netdisk"
    netdisk.mkdir()
    service = NetdiskSync(source, netdisk, logging.getLogger("test"))
    service.sync(today=date(2026, 6, 16))

    assert (netdisk / "markdown" / "2026-06" / "16" / "[UP][Title][BVxxx].md").exists()


def test_sync_old_month_to_archive_dir(tmp_path: Path):
    source = tmp_path / "data" / "markdown"
    source_day = source / "2026-05-30"
    source_day.mkdir(parents=True)
    (source_day / "[2026-05-30_10-00-00][UP][Title][BVxxx].md").write_text("x", encoding="utf-8")

    netdisk = tmp_path / "netdisk"
    netdisk.mkdir()
    service = NetdiskSync(source, netdisk, logging.getLogger("test"))
    service.sync(today=date(2026, 6, 16))

    assert (netdisk / "markdown" / "2026" / "05" / "30" / "[UP][Title][BVxxx].md").exists()

