from __future__ import annotations

import logging
import time
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
        upload_split_size_mb: int = 50,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.logger = logger
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self.upload_split_size_mb = upload_split_size_mb
        self.split_size_bytes = upload_split_size_mb * 1024 * 1024 if upload_split_size_mb > 0 else 0

    @classmethod
    def from_config(cls, config: AppConfig, logger: logging.Logger) -> "WebDavClient":
        password = config.secret("webdav.password")
        if not password:
            raise RuntimeError("缺失 WebDAV 密码；请设置 webdav.password_env 或 webdav.password")
        split_size = config.get("webdav.upload_split_size_mb", config.get("webdav.split_size_mb", 50))
        try:
            split_size_mb = int(split_size)
        except (TypeError, ValueError):
            split_size_mb = 50

        return cls(
            base_url=str(config.get("webdav.url")),
            username=str(config.get("webdav.username")),
            password=password,
            proxy=config.get("client.proxy") or None,
            upload_split_size_mb=split_size_mb,
            logger=logger,
        )

    def url_for(self, name: str) -> str:
        return f"{self.base_url}/{name}"

    def get_remote_file_size(self, remote_name: str) -> int | None:
        url = self.url_for(remote_name)
        try:
            resp = requests.head(
                url,
                auth=HTTPBasicAuth(self.username, self.password),
                headers={"Accept-Encoding": "identity"},
                timeout=15,
                proxies=self.proxies,
            )
            if resp.status_code == 200 and "Content-Length" in resp.headers:
                return int(resp.headers["Content-Length"])
        except Exception:
            pass
        return None

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

    def has_audio_files(self, bvid: str, remote_files: set[str] | None = None) -> bool:
        if remote_files is None:
            remote_files = self.list_files()
        for rf in remote_files:
            if rf == f"{bvid}.mp3" or rf.startswith(f"{bvid}.mp3.part"):
                return True
            if rf.startswith(f"{bvid}_") and ".mp3" in rf:
                return True
        return False

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
                if response.status_code == 200:
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    with local_path.open("wb") as file:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                file.write(chunk)
                    self.logger.info("WebDAV 下载成功: %s -> %s", remote_name, local_path)
                    return True
                elif response.status_code != 404:
                    response.raise_for_status()

            # 检查是否存在分片文件 (如 remote_name.part01)
            part01_name = f"{remote_name}.part01"
            part01_url = self.url_for(part01_name)
            self.logger.info("WebDAV 分片下载检查: %s", part01_url)
            with requests.get(
                part01_url,
                auth=HTTPBasicAuth(self.username, self.password),
                stream=True,
                timeout=30,
                proxies=self.proxies,
            ) as response:
                if response.status_code == 404:
                    self.logger.info("未在 WebDAV 上找到文件或分片: %s", remote_name)
                    return False
                if response.status_code != 200:
                    response.raise_for_status()

            self.logger.info("检测到分片文件存在，开始分片合并下载: %s", remote_name)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = local_path.with_suffix(local_path.suffix + ".downloading")
            
            try:
                part_idx = 1
                with temp_path.open("wb") as out_file:
                    while True:
                        part_name = f"{remote_name}.part{part_idx:02d}"
                        part_url = self.url_for(part_name)
                        with requests.get(
                            part_url,
                            auth=HTTPBasicAuth(self.username, self.password),
                            stream=True,
                            timeout=60,
                            proxies=self.proxies,
                        ) as part_resp:
                            if part_resp.status_code == 404:
                                break
                            if part_resp.status_code not in (200, 206):
                                self.logger.error("下载分片 %s 失败 status=%s", part_name, part_resp.status_code)
                                temp_path.unlink(missing_ok=True)
                                return False
                            for chunk in part_resp.iter_content(chunk_size=1024 * 1024):
                                if chunk:
                                    out_file.write(chunk)
                        self.logger.info("已下载分片: %s", part_name)
                        part_idx += 1

                if part_idx > 1:
                    temp_path.replace(local_path)
                    self.logger.info("分片下载完成并已合并: %s -> %s (共 %d 个分片)", remote_name, local_path, part_idx - 1)
                    return True
                else:
                    temp_path.unlink(missing_ok=True)
                    return False
            except Exception:
                temp_path.unlink(missing_ok=True)
                raise

        except requests.RequestException as exc:
            self.logger.warning("WebDAV 从 %s 下载失败: %s", remote_name, exc)
            return False

    def upload(self, local_path: Path, remote_name: str | None = None, show_progress: bool = False) -> bool:
        remote_name = remote_name or local_path.name
        file_size = local_path.stat().st_size

        if self.split_size_bytes > 0 and file_size > self.split_size_bytes:
            chunk_size = self.split_size_bytes
            total_parts = (file_size + chunk_size - 1) // chunk_size
            self.logger.info(
                "文件 %s 大小 %.2f MB 超过阈值 %.2f MB，将拆分为 %d 个分片上传",
                local_path.name,
                file_size / (1024 * 1024),
                chunk_size / (1024 * 1024),
                total_parts,
            )

            # 如果远端已存在未分片的同名旧文件，先尝试删除
            self._delete_single(remote_name)

            for part_idx in range(1, total_parts + 1):
                offset = (part_idx - 1) * chunk_size
                length = min(chunk_size, file_size - offset)
                part_name = f"{remote_name}.part{part_idx:02d}"
                part_url = self.url_for(part_name)

                # 断点续传：检查分片是否已完整存在于 WebDAV 上
                rem_size = self.get_remote_file_size(part_name)
                if rem_size is not None and rem_size == length:
                    self.logger.info("WebDAV 分片 %s 已存在且大小一致 (%d 字节)，跳过上传 (%d/%d)", part_name, rem_size, part_idx, total_parts)
                    continue

                self.logger.info("WebDAV 上传分片: %s (%d/%d) -> %s", part_name, part_idx, total_parts, part_url)

                max_part_retries = 3
                part_uploaded = False
                for retry_idx in range(1, max_part_retries + 1):
                    try:
                        with ChunkSliceFileWrapper(local_path, offset, length) as slice_file:
                            desc_text = f"正在上传 {part_name} ({part_idx}/{total_parts})"
                            if retry_idx > 1:
                                desc_text += f" [重试 {retry_idx}/{max_part_retries}]"

                            if show_progress:
                                from tqdm import tqdm

                                with tqdm(
                                    total=length,
                                    unit="B",
                                    unit_scale=True,
                                    unit_divisor=1024,
                                    desc=desc_text,
                                    leave=True,
                                ) as pbar:
                                    slice_file.callback = pbar.update
                                    response = requests.put(
                                        part_url,
                                        data=slice_file,
                                        auth=HTTPBasicAuth(self.username, self.password),
                                        headers={"Content-Type": "application/octet-stream"},
                                        timeout=300,
                                        proxies=self.proxies,
                                    )
                            else:
                                response = requests.put(
                                    part_url,
                                    data=slice_file,
                                    auth=HTTPBasicAuth(self.username, self.password),
                                    headers={"Content-Type": "application/octet-stream"},
                                    timeout=300,
                                    proxies=self.proxies,
                                )

                        if response.status_code in (200, 201, 204):
                            part_uploaded = True
                            self.logger.info("WebDAV 分片 %s 上传成功 (%d/%d)", part_name, part_idx, total_parts)
                            break
                        else:
                            self.logger.warning(
                                "WebDAV 分片 %s 上传返回状态码 %s (重试 %d/%d): %s",
                                part_name,
                                response.status_code,
                                retry_idx,
                                max_part_retries,
                                response.text,
                            )
                    except Exception as exc:
                        self.logger.warning("WebDAV 分片 %s 上传异常 (重试 %d/%d): %s", part_name, retry_idx, max_part_retries, exc)

                    if retry_idx < max_part_retries:
                        time.sleep(2)

                if not part_uploaded:
                    self.logger.error("WebDAV 分片 %s 经 %d 次尝试仍上传失败", part_name, max_part_retries)
                    return False

            self.logger.info("文件全量分片上传成功: %s (共 %d 个分片)", remote_name, total_parts)
            return True

        # 不超过阈值，直接单文件上传
        url = self.url_for(remote_name)
        self.logger.info("WebDAV 上传: %s -> %s", local_path, url)

        # 上传前清理可能残留的分片
        self._delete_parts(remote_name)

        max_retries = 3
        for retry_idx in range(1, max_retries + 1):
            try:
                with local_path.open("rb") as raw_file:
                    desc_text = f"正在上传 {local_path.name}"
                    if retry_idx > 1:
                        desc_text += f" [重试 {retry_idx}/{max_retries}]"

                    if show_progress:
                        from tqdm import tqdm

                        with tqdm(
                            total=file_size,
                            unit="B",
                            unit_scale=True,
                            unit_divisor=1024,
                            desc=desc_text,
                            leave=True,
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
                self.logger.warning("WebDAV 上传失败 status=%s body=%s (重试 %d/%d)", response.status_code, response.text, retry_idx, max_retries)
            except Exception as exc:
                self.logger.warning("WebDAV 上传 %s 异常 (重试 %d/%d): %s", local_path, retry_idx, max_retries, exc)

            if retry_idx < max_retries:
                time.sleep(2)

        self.logger.error("WebDAV 上传 %s 失败（已尝试 %d 次）", local_path, max_retries)
        return False

    def delete(self, remote_url_or_name: str) -> bool:
        url = remote_url_or_name if remote_url_or_name.startswith("http") else self.url_for(remote_url_or_name)
        name = remote_url_or_name if not remote_url_or_name.startswith("http") else remote_url_or_name.rstrip("/").rsplit("/", 1)[-1]
        self.logger.info("WebDAV 删除: %s", url)

        ok = self._delete_single(url)

        # 如果传入的是原文件名 (非 .part 文件)，同时清理可能存在的分片文件
        if ".part" not in name:
            self._delete_parts(name)

        return ok

    def _delete_single(self, remote_url_or_name: str) -> bool:
        url = remote_url_or_name if remote_url_or_name.startswith("http") else self.url_for(remote_url_or_name)
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

    def _delete_parts(self, remote_name: str) -> None:
        for idx in range(1, 100):
            part_name = f"{remote_name}.part{idx:02d}"
            part_url = self.url_for(part_name)
            try:
                resp = requests.delete(
                    part_url,
                    auth=HTTPBasicAuth(self.username, self.password),
                    timeout=30,
                    proxies=self.proxies,
                )
                if resp.status_code == 404:
                    break
            except Exception:
                break


class CallbackFileWrapper:
    def __init__(self, file, callback, size):
        self.file = file
        self.callback = callback
        self.size = size

    def read(self, size=-1):
        data = self.file.read(size)
        if data and self.callback:
            self.callback(len(data))
        return data

    def __len__(self):
        return self.size

    def seek(self, offset, whence=0):
        return self.file.seek(offset, whence)

    def tell(self):
        return self.file.tell()


class ChunkSliceFileWrapper:
    def __init__(self, file_path: Path, offset: int, length: int, callback=None):
        self.file_path = file_path
        self.offset = offset
        self.length = length
        self.callback = callback
        self.bytes_read = 0
        self._file = file_path.open("rb")
        self._file.seek(offset)

    def read(self, size=-1):
        if self.bytes_read >= self.length:
            return b""
        remaining = self.length - self.bytes_read
        to_read = remaining if size < 0 or size > remaining else size
        data = self._file.read(to_read)
        if data:
            self.bytes_read += len(data)
            if self.callback:
                self.callback(len(data))
        return data

    def seek(self, offset, whence=0):
        if whence == 0:
            target = offset
        elif whence == 1:
            target = self.bytes_read + offset
        elif whence == 2:
            target = self.length + offset
        else:
            raise ValueError(f"Invalid whence: {whence}")
        target = max(0, min(self.length, target))
        self._file.seek(self.offset + target)
        self.bytes_read = target
        return self.bytes_read

    def tell(self):
        return self.bytes_read

    def __len__(self):
        return self.length

    def close(self):
        if self._file and not self._file.closed:
            self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
