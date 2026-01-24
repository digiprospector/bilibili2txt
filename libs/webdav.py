#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebDAV 工具模块 - 统一管理 WebDAV 文件操作

主要功能:
- 文件上传/下载（带进度条）
- 文件删除/存在检查
- 目录列表获取
"""

from pathlib import Path
from typing import Optional, Union
from xml.etree import ElementTree

import requests
from requests.auth import HTTPBasicAuth
from tqdm import tqdm


def _get_proxies(proxy: Optional[str]) -> Optional[dict]:
    """构建代理配置字典"""
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def upload_to_webdav_requests(
    url: str, 
    username: str, 
    password: str, 
    file_path: Path, 
    logger,
    webdav_proxy: Optional[str] = None
) -> bool:
    """
    上传文件到 WebDAV，显示进度条
    
    Args:
        url: WebDAV 文件 URL
        username: 用户名
        password: 密码
        file_path: 本地文件路径
        logger: 日志记录器
        webdav_proxy: 代理地址（可选）
        
    Returns:
        上传是否成功
    """
    try:
        proxies = _get_proxies(webdav_proxy)
        if proxies:
            logger.info(f"使用 WebDAV 代理: {webdav_proxy}")

        file_size = file_path.stat().st_size
        file_name = file_path.name

        with file_path.open('rb') as file:
            with tqdm.wrapattr(
                file, "read", 
                total=file_size, 
                unit='B', 
                unit_scale=True, 
                unit_divisor=1024, 
                desc=f"上传中: {file_name}"
            ) as file_with_progress:
                response = requests.put(
                    url,
                    data=file_with_progress,
                    auth=HTTPBasicAuth(username, password),
                    headers={'Content-Type': 'application/octet-stream'},
                    proxies=proxies
                )
        
        if response.status_code in (200, 201, 204):
            logger.info(f"\n文件上传成功！状态码: {response.status_code}")
            return True
        
        logger.error(f"\n上传失败，状态码：{response.status_code}")
        logger.error(f"响应内容：{response.text}")
        return False
        
    except Exception as e:
        logger.error(f"上传过程中发生异常: {e}")
        return False


def download_from_webdav_requests(
    url: str, 
    username: str, 
    password: str, 
    local_file_path: Path, 
    logger,
    webdav_proxy: Optional[str] = None
) -> bool:
    """
    从 WebDAV 下载文件，显示进度条
    
    Args:
        url: WebDAV 文件 URL
        username: 用户名
        password: 密码
        local_file_path: 本地保存路径
        logger: 日志记录器
        webdav_proxy: 代理地址（可选）
        
    Returns:
        下载是否成功
    """
    try:
        proxies = _get_proxies(webdav_proxy)
        
        with requests.get(
            url, 
            auth=HTTPBasicAuth(username, password), 
            stream=True, 
            timeout=30,
            proxies=proxies
        ) as r:
            r.raise_for_status()
            
            total_size = int(r.headers.get('content-length', 0))
            file_name = local_file_path.name
            
            with tqdm(
                total=total_size, 
                unit='B', 
                unit_scale=True, 
                desc=f"下载中: {file_name}"
            ) as progress_bar:
                with open(local_file_path, 'wb') as file:
                    for chunk in r.iter_content(chunk_size=8192):
                        file.write(chunk)
                        progress_bar.update(len(chunk))

        logger.info(f"\n文件下载成功: {local_file_path}")
        return True
        
    except requests.exceptions.RequestException as e:
        logger.error(f"\n下载失败: {e}")
        return False


def delete_from_webdav_requests(
    url: str, 
    username: str, 
    password: str, 
    logger,
    webdav_proxy: Optional[str] = None
) -> bool:
    """
    从 WebDAV 删除文件
    
    Args:
        url: 要删除的文件 URL
        username: 用户名
        password: 密码
        logger: 日志记录器
        webdav_proxy: 代理地址（可选）
        
    Returns:
        删除是否成功（文件不存在也视为成功）
    """
    try:
        proxies = _get_proxies(webdav_proxy)
        if proxies:
            logger.info(f"使用 WebDAV 代理: {webdav_proxy}")

        response = requests.delete(
            url, 
            auth=(username, password), 
            timeout=60, 
            proxies=proxies
        )

        if response.status_code == 204:
            logger.info(f"成功从 WebDAV 删除文件: {url}")
            return True
        
        if response.status_code == 404:
            logger.warning(f"尝试从 WebDAV 删除文件时未找到 (404)，视为操作成功: {url}")
            return True
        
        logger.error(f"从 WebDAV 删除文件失败: {url} (状态码: {response.status_code}) - {response.text}")
        return False
        
    except requests.exceptions.RequestException as e:
        logger.error(f"从 WebDAV 删除文件时发生网络错误: {e}")
        return False


def check_webdav_file_exists(
    url: str, 
    username: str, 
    password: str, 
    logger,
    webdav_proxy: Optional[str] = None
) -> bool:
    """
    检查 WebDAV 文件是否存在
    
    Args:
        url: 文件 URL
        username: 用户名
        password: 密码
        logger: 日志记录器
        webdav_proxy: 代理地址（可选）
        
    Returns:
        文件是否存在
    """
    try:
        proxies = _get_proxies(webdav_proxy)
        response = requests.head(
            url, 
            auth=(username, password), 
            timeout=10, 
            proxies=proxies
        )
        return response.status_code == 200
        
    except requests.exceptions.RequestException as e:
        logger.error(f"检查 WebDAV 文件是否存在时发生网络错误 ({url}): {e}")
        return False


def list_webdav_files(
    url: str, 
    username: str, 
    password: str, 
    logger,
    webdav_proxy: Optional[str] = None,
    return_full_url: bool = False
) -> Union[list[str], set[str], None]:
    """
    获取 WebDAV 目录下的文件列表
    
    Args:
        url: WebDAV 目录 URL
        username: 用户名
        password: 密码
        logger: 日志记录器
        webdav_proxy: 代理地址（可选）
        return_full_url: True 返回完整 URL 列表，False 返回文件名集合
        
    Returns:
        文件列表或文件名集合，失败返回空列表或 None
    """
    logger.info(f"正在从 WebDAV 获取文件列表: {url}")
    proxies = _get_proxies(webdav_proxy)
    
    try:
        response = requests.request(
            "PROPFIND",
            url,
            auth=(username, password),
            headers={"Depth": "1"},
            proxies=proxies,
            timeout=30
        )
        response.raise_for_status()
        
        # 解析 XML 响应
        root = ElementTree.fromstring(response.content)
        ns = {'d': 'DAV:'}
        
        base_url = url.rstrip('/')
        results = []
        
        for href in root.findall('.//d:href', ns):
            href_text = href.text
            # 跳过目录自身（以 / 结尾）
            if href_text.endswith('/'):
                continue
            filename = Path(href_text).name
            if return_full_url:
                results.append(f"{base_url}/{filename}")
            else:
                results.append(filename)
        
        logger.info(f"从 WebDAV 成功获取 {len(results)} 个文件。")
        return results if return_full_url else set(results)
        
    except requests.exceptions.RequestException as e:
        logger.error(f"从 WebDAV 获取文件列表失败: {e}")
        return [] if return_full_url else None
    except Exception as e:
        logger.error(f"解析 WebDAV 列表失败: {e}")
        return [] if return_full_url else None