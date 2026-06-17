from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .paths import ROOT_DIR, resolve_path


DEFAULT_CONFIG_FILES = (
    ROOT_DIR / "data" / "config.yaml",
    ROOT_DIR / "config.yaml",
    ROOT_DIR / "config.example.yaml",
)


@dataclass(frozen=True)
class AppConfig:
    root_dir: Path
    config_path: Path | None
    raw: dict[str, Any]

    @property
    def data_dir(self) -> Path:
        return self.path("data.repo_dir", "data")

    @property
    def queue_dir(self) -> Path:
        return self.path("queue.repo_dir", "queue")

    @property
    def temp_dir(self) -> Path:
        return self.path("app.temp_dir", "temp")

    @property
    def logs_dir(self) -> Path:
        return self.path("app.logs_dir", "logs")

    def get(self, dotted_key: str, default: Any = None) -> Any:
        current: Any = self.raw
        for part in dotted_key.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def path(self, dotted_key: str, default: str | Path | None = None) -> Path:
        value = self.get(dotted_key, default)
        if value is None:
            raise ConfigError(f"Missing config path: {dotted_key}")
        return resolve_path(value, self.root_dir)

    def secret(self, dotted_key: str, default: str | None = None) -> str | None:
        value = self.get(dotted_key)
        env_key = self.get(f"{dotted_key}_env")
        if env_key:
            return os.environ.get(env_key, default)
        if value is None:
            return default
        return str(value)


class ConfigError(RuntimeError):
    pass


def load_config(config_path: str | Path | None = None) -> AppConfig:
    path = _select_config_path(config_path)
    raw = _load_yaml(path) if path else {}
    return AppConfig(root_dir=ROOT_DIR, config_path=path, raw=raw)


def _select_config_path(config_path: str | Path | None) -> Path | None:
    if config_path:
        path = resolve_path(config_path, ROOT_DIR)
        if not path.exists():
            raise ConfigError(f"Config file does not exist: {path}")
        return path

    for path in DEFAULT_CONFIG_FILES:
        if path.exists():
            return path
    return None


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML config {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"Config root must be a mapping: {path}")
    return data


DB_FILENAME = "bilibili2txt.db"


@dataclass(frozen=True)
class CommandContext:
    config: AppConfig
    command_name: str
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.config.data_dir / DB_FILENAME

    def database(self):
        from .database import ClientDatabase

        db = ClientDatabase(self.db_path)
        db.initialize()
        return db

    def queue(self, logger: logging.Logger, *, sync: bool = True):
        from .services.gitqueue import GitQueue

        q = GitQueue(self.config.queue_dir, logger)
        q.ensure_layout()
        if sync:
            q.sync()
        return q

    def server_id(self, args) -> str:
        return args.server_id or self.config.get("server.server_id", "default-server")

    def netdisk_sync(self, logger: logging.Logger):
        from .services.netdisk import NetdiskSync

        netdisk_dir = self.config.path("client.netdisk_dir")
        return NetdiskSync(self.config.data_dir / "markdown", netdisk_dir, logger)

