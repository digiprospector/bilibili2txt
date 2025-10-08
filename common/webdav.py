from pathlib import Path
from tqdm import tqdm
import requests
from requests.auth import HTTPBasicAuth

def upload_to_webdav_requests(url, username, password, file_path: Path, logger):
    """
    使用requests库上传文件到WebDAV，并显示进度条。
    """
    try:
        # 使用 pathlib 获取文件大小和文件名
        file_size = file_path.stat().st_size
        file_name = file_path.name

        with file_path.open('rb') as file:
            # 使用tqdm.wrapattr包装文件对象，以监控read()操作
            with tqdm.wrapattr(file, "read", total=file_size, unit='B', unit_scale=True, unit_divisor=1024, desc=f"上传中: {file_name}") as file_with_progress:
                response = requests.put(
                    url,
                    data=file_with_progress,
                    auth=HTTPBasicAuth(username, password),
                    headers={'Content-Type': 'application/octet-stream'}
                )
        
        if response.status_code in [200, 201, 204]:
            logger.info(f"\n文件上传成功！状态码: {response.status_code}")
            return True
        else:
            logger.error(f"\n上传失败，状态码：{response.status_code}")
            logger.error(f"响应内容：{response.text}")
            return False
    except Exception as e:
        logger.error(f"上传过程中发生异常: {e}")
        return False

def download_from_webdav_requests(url: str, username: str, password: str, local_file_path: Path, logger):
    """
    使用requests库从WebDAV下载文件，并显示进度条。
    :return: bool, True表示下载成功, False表示失败。
    """
    try:
        with requests.get(url, auth=HTTPBasicAuth(username, password), stream=True, timeout=30) as r:
            r.raise_for_status()  # 如果状态码不是2xx，则引发HTTPError
            
            total_size = int(r.headers.get('content-length', 0))
            block_size = 8192 # 8KB
            
            file_name = local_file_path.name
            
            with tqdm(total=total_size, unit='B', unit_scale=True, desc=f"下载中: {file_name}") as progress_bar:
                with open(local_file_path, 'wb') as file:
                    for chunk in r.iter_content(chunk_size=block_size):
                        file.write(chunk)
                        progress_bar.update(len(chunk))

        logger.info(f"\n文件下载成功: {local_file_path}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"\n下载失败: {e}")
        return False

# 请将此函数添加到 common/webdav.py 文件中

def delete_from_webdav_requests(url: str, username: str, password: str, logger) -> bool:
    """
    使用 requests 从 WebDAV 服务器删除文件。

    Args:
        url (str): 要删除的文件的完整 URL。
        username (str): WebDAV 用户名。
        password (str): WebDAV 密码。
        logger: 用于记录日志的 logger 对象。

    Returns:
        bool: 如果删除成功或文件不存在，则返回 True，否则返回 False。
    """
    try:
        response = requests.delete(url, auth=(username, password), timeout=60)

        # 204 No Content 表示成功删除
        if response.status_code == 204:
            logger.info(f"成功从 WebDAV 删除文件: {url}")
            return True
        # 404 Not Found 也可视为成功，因为目标是确保文件不存在
        elif response.status_code == 404:
            logger.warning(f"尝试从 WebDAV 删除文件时未找到 (404)，视为操作成功: {url}")
            return True
        else:
            logger.error(f"从 WebDAV 删除文件失败: {url} (状态码: {response.status_code}) - {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        logger.error(f"从 WebDAV 删除文件时发生网络错误: {e}")
        return False

def check_webdav_file_exists(url: str, username: str, password: str, logger) -> bool:
    """
    使用 requests.head() 检查 WebDAV 服务器上是否存在文件。

    Args:
        url (str): 要检查的文件的完整 URL。
        username (str): WebDAV 用户名。
        password (str): WebDAV 密码。
        logger: 用于记录日志的 logger 对象。

    Returns:
        bool: 如果文件存在，则返回 True，否则返回 False。
    """
    try:
        response = requests.head(url, auth=(username, password), timeout=10)
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        logger.error(f"检查 WebDAV 文件是否存在时发生网络错误 ({url}): {e}")
        return False


    