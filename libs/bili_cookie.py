#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bilibili cookie 工具模块

提供从 userdata/bili_cookies.json 读取 cookie 并生成 Netscape 格式 cookie 文件的功能，
供 yt-dlp 通过 cookiefile 选项使用。
"""

import json
import logging
from pathlib import Path
from typing import Optional

try:
    from env import get_path
    _USERDATA_DIR: Optional[Path] = None
    _TEMP_DIR: Optional[Path] = None

    def _get_userdata_dir() -> Path:
        global _USERDATA_DIR
        if _USERDATA_DIR is None:
            try:
                _USERDATA_DIR = get_path("userdata_dir")
            except Exception:
                _USERDATA_DIR = Path(__file__).resolve().parent.parent / "data" / "userdata"
        return _USERDATA_DIR

    def _get_temp_dir() -> Path:
        global _TEMP_DIR
        if _TEMP_DIR is None:
            try:
                _TEMP_DIR = get_path("temp_dir")
            except Exception:
                _TEMP_DIR = Path(__file__).resolve().parent.parent / "temp"
        return _TEMP_DIR

except ImportError:
    def _get_userdata_dir() -> Path:
        return Path(__file__).resolve().parent.parent / "data" / "userdata"

    def _get_temp_dir() -> Path:
        return Path(__file__).resolve().parent.parent / "temp"


def get_bili_cookie_file(
    logger: Optional[logging.Logger] = None,
    cookie_filename: str = "bili_cookies.json",
) -> Optional[Path]:
    """
    读取 userdata/{cookie_filename}，将其转换为 Netscape 格式 cookie 文件（写入 temp 目录）。

    Args:
        logger: 可选的日志对象，用于输出加载状态。
        cookie_filename: JSON cookie 文件名，默认为 'bili_cookies.json'。
                         server 端可传入 'server_bili_cookies.json'。

    Returns:
        Netscape cookie 文件路径，若 JSON 文件不存在或读取失败则返回 None。
    """
    cookies_json = _get_userdata_dir() / cookie_filename
    if not cookies_json.exists():
        return None
    try:
        # Netscape 文件名与 JSON 文件名对应（换扩展名为 .txt）
        netscape_file = _get_temp_dir() / (Path(cookie_filename).stem + ".txt")
        netscape_file.parent.mkdir(parents=True, exist_ok=True)

        # 若 txt 文件存在且比 JSON 新，直接复用，无需重新生成
        if netscape_file.exists() and netscape_file.stat().st_mtime >= cookies_json.stat().st_mtime:
            return netscape_file

        with open(cookies_json, 'r', encoding='utf-8') as f:
            cookies = json.load(f)

        with open(netscape_file, 'w', encoding='utf-8') as f:
            f.write("# Netscape HTTP Cookie File\n")
            for name, value in cookies.items():
                # 格式: domain \t includeSubdomains \t path \t secure \t expiry \t name \t value
                f.write(f".bilibili.com\tTRUE\t/\tFALSE\t0\t{name}\t{value}\n")

        if logger:
            logger.info(f"已加载 {cookie_filename}，共 {len(cookies)} 个 cookie")
        return netscape_file
    except Exception as e:
        if logger:
            logger.warning(f"加载 {cookie_filename} 失败，将不使用 cookie: {e}")
        return None


def apply_bili_cookies_to_ydl_opts(
    ydl_opts: dict,
    logger: Optional[logging.Logger] = None,
    cookie_filename: str = "bili_cookies.json",
) -> dict:
    """
    若指定的 cookie JSON 文件存在，将 Netscape cookie 文件路径注入 yt-dlp 的 cookiefile 选项。

    Args:
        ydl_opts: yt-dlp 选项字典（会在原地修改并返回）。
        logger: 可选的日志对象。
        cookie_filename: JSON cookie 文件名，默认为 'bili_cookies.json'。
                         server 端可传入 'server_bili_cookies.json'。

    Returns:
        更新后的 ydl_opts 字典。
    """
    cookie_file = get_bili_cookie_file(logger=logger, cookie_filename=cookie_filename)
    if cookie_file:
        ydl_opts['cookiefile'] = str(cookie_file)
    return ydl_opts
