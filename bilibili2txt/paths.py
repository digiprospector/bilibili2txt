from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


def resolve_path(value: str | Path, base_dir: Path = ROOT_DIR) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return base_dir / path

