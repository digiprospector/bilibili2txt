from __future__ import annotations

import logging
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth

from ..config import AppConfig


class WebDavClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        logger: logging.Logger,
        proxy: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.logger = logger
        self.proxies = {"http": proxy, "https": proxy} if proxy else None

    @classmethod
    def from_config(cls, config: AppConfig, logger: logging.Logger) -> "WebDavClient":
        password = config.secret("webdav.password")
        if not password:
            raise RuntimeError("缺失 WebDAV 密码；请设置 webdav.password_env 或 webdav.password")
        return cls(
            base_url=str(config.get("webdav.url")),
            username=str(config.get("webdav.username")),
            password=password,
            proxy=config.get("webdav.proxy") or None,
            logger=logger,
        )

    def url_for(self, name: str) -> str:
        return f"{self.base_url}/{name}"

    def list_files(self) -> set[str]:
        self.logger.info("获取 WebDAV 文件列表: %s", self.base_url)
        try:
            response = requests.request(
                "PROPFIND",
                self.base_url + "/",
                auth=HTTPBasicAuth(self.username, self.password),
                headers={"Depth": "1"},
                timeout=30,
                proxies=self.proxies,
            )
            if response.status_code not in (207, 200):
                self.logger.warning("WebDAV PROPFIND 失败 status=%s", response.status_code)
                return set()
            import re
            hrefs = re.findall(r"<d:href>([^<]+)</d:href>", response.text, re.IGNORECASE)
            if not hrefs:
                hrefs = re.findall(r"<href>([^<]+)</href>", response.text, re.IGNORECASE)
            from urllib.parse import unquote
            names = set()
            for href in hrefs:
                name = unquote(href.rstrip("/").rsplit("/", 1)[-1])
                if name and "." in name:
                    names.add(name)
            self.logger.info("WebDAV 上已有 %d 个文件", len(names))
            return names
        except requests.RequestException as exc:
            self.logger.warning("WebDAV 列出文件失败: %s", exc)
            return set()

    def download(self, remote_name: str, local_path: Path) -> bool:
        url = self.url_for(remote_name)
        self.logger.info("WebDAV 下载检查: %s", url)
        try:
            with requests.get(
                url,
                auth=HTTPBasicAuth(self.username, self.password),
                stream=True,
                timeout=30,
                proxies=self.proxies,
            ) as response:
                if response.status_code == 404:
                    self.logger.info("未在 WebDAV 上找到文件: %s", remote_name)
                    return False
                response.raise_for_status()
                local_path.parent.mkdir(parents=True, exist_ok=True)
                with local_path.open("wb") as file:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            file.write(chunk)
            self.logger.info("WebDAV 下载成功: %s -> %s", remote_name, local_path)
            return True
        except requests.RequestException as exc:
            self.logger.warning("WebDAV 从 %s 下载失败: %s", remote_name, exc)
            return False

    def upload(self, local_path: Path, remote_name: str | None = None, show_progress: bool = False) -> bool:
        remote_name = remote_name or local_path.name
        url = self.url_for(remote_name)
        self.logger.info("WebDAV 上传: %s -> %s", local_path, url)
        
        file_size = local_path.stat().st_size
        try:
            with local_path.open("rb") as raw_file:
                if show_progress:
                    from tqdm import tqdm
                    
                    with tqdm(
                        total=file_size,
                        unit="B",
                        unit_scale=True,
                        unit_divisor=1024,
                        desc=f"正在上传 {local_path.name}",
                        leave=True
                    ) as pbar:
                        wrapped_file = CallbackFileWrapper(raw_file, pbar.update, file_size)
                        response = requests.put(
                            url,
                            data=wrapped_file,
                            auth=HTTPBasicAuth(self.username, self.password),
                            headers={"Content-Type": "application/octet-stream"},
                            timeout=300,
                            proxies=self.proxies,
                        )
                else:
                    response = requests.put(
                        url,
                        data=raw_file,
                        auth=HTTPBasicAuth(self.username, self.password),
                        headers={"Content-Type": "application/octet-stream"},
                        timeout=300,
                        proxies=self.proxies,
                    )
                    
            if response.status_code in (200, 201, 204):
                self.logger.info("WebDAV 上传成功: %s", remote_name)
                return True
            self.logger.error("WebDAV 上传失败 status=%s body=%s", response.status_code, response.text)
            return False
        except Exception as exc:
            self.logger.error("WebDAV 上传 %s 失败: %s", local_path, exc)
            return False

    def delete(self, remote_url_or_name: str) -> bool:
        url = remote_url_or_name if remote_url_or_name.startswith("http") else self.url_for(remote_url_or_name)
        self.logger.info("WebDAV 删除: %s", url)
        try:
            response = requests.delete(
                url,
                auth=HTTPBasicAuth(self.username, self.password),
                timeout=60,
                proxies=self.proxies,
            )
            if response.status_code in (204, 404):
                return True
            self.logger.error("WebDAV 删除失败 status=%s body=%s", response.status_code, response.text)
            return False
        except requests.RequestException as exc:
            self.logger.error("WebDAV 删除失败: %s", exc)
            return False


class CallbackFileWrapper:
    def __init__(self, file, callback, size):
        self.file = file
        self.callback = callback
        self.size = size

    def read(self, size=-1):
        data = self.file.read(size)
        if data:
            self.callback(len(data))
        return data

    def __len__(self):
        return self.size

    def seek(self, offset, whence=0):
        return self.file.seek(offset, whence)

    def tell(self):
        return self.file.tell()
