#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from concurrent.futures import ThreadPoolExecutor

from bootstrap import config, get_standard_logger
from webdav import list_webdav_files, delete_from_webdav_requests

# 日志
logger = get_standard_logger(__file__)

def clean_webdav():
    """
    删除 WebDAV 服务器上的所有文件。
    """
    webdav_url = config.get('webdav_url')
    username = config.get('webdav_username')
    password = config.get('webdav_password')
    webdav_proxy = config.get('webdav_proxy')

    if not all([webdav_url, username, password]):
        logger.error("WebDAV 配置缺失 (webdav_url, webdav_username, webdav_password)。")
        return

    # 获取所有文件的完整 URL
    files_to_delete = list_webdav_files(webdav_url, username, password, logger, webdav_proxy, return_full_url=True)
    
    if not files_to_delete:
        logger.info("WebDAV 上没有文件需要删除。")
        return

    logger.info(f"准备删除 {len(files_to_delete)} 个文件...")
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        for file_url in files_to_delete:
            logger.info(f"正在删除: {file_url}")
            executor.submit(
                delete_from_webdav_requests, 
                url=file_url, 
                username=username, 
                password=password, 
                logger=logger, 
                webdav_proxy=webdav_proxy
            )
    
    logger.info("WebDAV 清理完成。")

if __name__ == "__main__":
    clean_webdav()