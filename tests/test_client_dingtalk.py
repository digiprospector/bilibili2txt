from __future__ import annotations

import logging
import time
from argparse import Namespace
from pathlib import Path
import pytest

from bilibili2txt.commands import client as client_commands
from bilibili2txt.config import CommandContext, load_config

def _context(tmp_path: Path, dingtalk_config: str = "") -> CommandContext:
    config_path = tmp_path / "config.yaml"
    config_lines = [
        "app:",
        f"  temp_dir: {(tmp_path / 'temp').as_posix()}",
        "  logs_dir: logs",
        "data:",
        f"  repo_dir: {(tmp_path / 'data').as_posix()}",
        "queue:",
        f"  repo_dir: {(tmp_path / 'queue').as_posix()}",
        "client:"
    ]
    if dingtalk_config:
        config_lines.append(dingtalk_config)
    
    config_path.write_text("\n".join(config_lines) + "\n", encoding="utf-8")
    return CommandContext(load_config(config_path), "client run")

def test_dingtalk_not_sent_when_disabled(tmp_path: Path, monkeypatch):
    called = []
    
    import requests
    def mock_post(url, json, timeout):
        called.append((url, json))
        class MockResponse:
            def raise_for_status(self): pass
            def json(self): return {"errcode": 0}
        return MockResponse()
        
    monkeypatch.setattr(requests, "post", mock_post)
    
    # Mock all commands client.run executes
    monkeypatch.setattr(client_commands, "scan", lambda *a: 0)
    monkeypatch.setattr(client_commands, "prepare_audio", lambda *a: 0)
    monkeypatch.setattr(client_commands, "submit", lambda *a: 0)
    
    ctx = _context(tmp_path, "    dingtalk:\n      enabled: false\n      webhook: http://mock")
    args = Namespace(wait=False, skip_env_check=True, skip_scan=True)
    
    code = client_commands.run(ctx, args, logging.getLogger("test"))
    assert code == 0
    assert len(called) == 0

def test_dingtalk_sent_when_enabled(tmp_path: Path, monkeypatch):
    called = []
    
    import requests
    def mock_post(url, json, timeout):
        called.append((url, json))
        class MockResponse:
            def raise_for_status(self): pass
            def json(self): return {"errcode": 0}
        return MockResponse()
        
    monkeypatch.setattr(requests, "post", mock_post)
    
    # Mock all commands client.run executes
    monkeypatch.setattr(client_commands, "scan", lambda *a: 0)
    monkeypatch.setattr(client_commands, "prepare_audio", lambda *a: 0)
    monkeypatch.setattr(client_commands, "submit", lambda *a: 0)
    
    ctx = _context(tmp_path, "    dingtalk:\n      enabled: true\n      webhook: http://mock-webhook\n      secret: mock-secret")
    args = Namespace(wait=False, skip_env_check=True, skip_scan=True)
    
    # Inject some mock stats into extra
    ctx.extra["scan_stats"] = {"created": 2, "skipped": 1}
    ctx.extra["sync_stats"] = {"copied": 1, "skipped": 0, "conflicts": 0, "archived": 0}
    
    code = client_commands.run(ctx, args, logging.getLogger("test"))
    assert code == 0
    assert len(called) == 1
    url, json_data = called[0]
    
    # Assert signature exists
    assert "timestamp=" in url
    assert "sign=" in url
    assert json_data["msgtype"] == "markdown"
    assert "客户端运行结束" in json_data["markdown"]["text"]
    assert "扫描视频**: 新增 2 个" in json_data["markdown"]["text"]
    assert "网盘同步**: 同步 1 个" in json_data["markdown"]["text"]
