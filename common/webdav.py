from pathlib import Path
from tqdm import tqdm
import requests
from requests.auth import HTTPBasicAuth
from xml.etree import ElementTree

def upload_to_webdav_requests(url, username, password, file_path: Path, logger, webdav_proxy: str = None):
    """
    使用requests库上传文件到WebDAV，并显示进度条。
    """
    try:
        proxies = None
        if webdav_proxy:
            proxies = {
                "http": webdav_proxy,
                "https": webdav_proxy,
            }
            logger.info(f"使用 WebDAV 代理: {webdav_proxy}")

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
                    headers={'Content-Type': 'application/octet-stream'},
                    proxies=proxies
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

def delete_from_webdav_requests(url: str, username: str, password: str, logger, webdav_proxy: str = None) -> bool:
    """
    使用 requests 从 WebDAV 服务器删除文件。

    Args:
        url (str): 要删除的文件的完整 URL。
        username (str): WebDAV 用户名。
        password (str): WebDAV 密码。
        logger: 用于记录日志的 logger 对象。
        webdav_proxy (str): WebDAV 代理地址。

    Returns:
        bool: 如果删除成功或文件不存在，则返回 True，否则返回 False。
    """
    try:
        proxies = None
        if webdav_proxy:
            proxies = {
                "http": webdav_proxy,
                "https": webdav_proxy,
            }
            logger.info(f"使用 WebDAV 代理: {webdav_proxy}")

        response = requests.delete(url, auth=(username, password), timeout=60, proxies=proxies)

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

def check_webdav_file_exists(url: str, username: str, password: str, logger, webdav_proxy: str = None) -> bool:
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
        proxies = None
        if webdav_proxy:
            proxies = {
                "http": webdav_proxy,
                "https": webdav_proxy,
            }
            # 检查文件时，代理信息可能比较敏感或冗余，可以选择不打印日志

        response = requests.head(url, auth=(username, password), timeout=10, proxies=proxies)
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        logger.error(f"检查 WebDAV 文件是否存在时发生网络错误 ({url}): {e}")
        return False

def list_webdav_files(url, username, password, logger, webdav_proxy=None, return_full_url=False):
    """获取WebDAV服务器上指定路径下的文件列表
    
    Args:
        return_full_url: 如果为 True，返回完整 URL 列表；否则返回文件名集合。
    """
    logger.info(f"正在从 WebDAV 获取文件列表: {url}")
    proxies = {'http': webdav_proxy, 'https': webdav_proxy} if webdav_proxy else None
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
        
        # 解析XML响应
        root = ElementTree.fromstring(response.content)
        ns = {'d': 'DAV:'}
        
        base_url = url.rstrip('/')
        results = []
        
        for href in root.findall('.//d:href', ns):
            href_text = href.text
            # 跳过目录自身 (以 / 结尾)
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