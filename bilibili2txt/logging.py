from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logger(
    name: str,
    logs_dir: Path,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
) -> logging.Logger:
    logs_dir.mkdir(parents=True, exist_ok=True)
    command_logs_dir = logs_dir / "commands"
    command_logs_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(console_level)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    main_file = RotatingFileHandler(
        logs_dir / "b2t.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    main_file.setLevel(file_level)
    main_file.setFormatter(formatter)
    logger.addHandler(main_file)

    command_file = RotatingFileHandler(
        command_logs_dir / f"{name}.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    command_file.setLevel(file_level)
    command_file.setFormatter(formatter)
    logger.addHandler(command_file)

    return logger


def log_command_start(logger: logging.Logger, command_name: str, config_path: Path | None) -> None:
    logger.info("=" * 72)
    logger.info("Command: %s", command_name)
    logger.info("Config: %s", config_path if config_path else "<defaults only>")


def log_command_finish(
    logger: logging.Logger,
    command_name: str,
    succeeded: int = 0,
    skipped: int = 0,
    failed: int = 0,
) -> None:
    logger.info(
        "Finished %s: succeeded=%s skipped=%s failed=%s",
        command_name,
        succeeded,
        skipped,
        failed,
    )
    logger.info("=" * 72)

