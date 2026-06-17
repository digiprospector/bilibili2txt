from __future__ import annotations

import logging
from pathlib import Path

import yt_dlp

from ..config import AppConfig
from ..models import Task
from .webdav import WebDavClient


class AudioError(RuntimeError):
    pass


class AudioService:
    def __init__(self, config: AppConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.audio_dir = config.temp_dir / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)

    def get_audio_files_for_server(self, task: Task) -> list[Path]:
        self._clean_task_audio(task)
        webdav = WebDavClient.from_config(self.config, self.logger)
        files = self._download_from_webdav(task, webdav)
        if files:
            return files
        return self._download_with_ytdlp(task)

    def download_task_audio(self, task: Task) -> list[Path]:
        self._clean_task_audio(task)
        return self._download_with_ytdlp(task)

    def upload_task_audio(self, task: Task, audio_files: list[Path], show_progress: bool = True) -> bool:
        webdav = WebDavClient.from_config(self.config, self.logger)
        ok = True
        for index, audio_file in enumerate(audio_files, start=1):
            remote_name = f"{task.bvid}.mp3" if len(audio_files) == 1 else f"{task.bvid}_{index}.mp3"
            if not webdav.upload(audio_file, remote_name, show_progress=show_progress):
                ok = False
                continue
            audio_file.unlink(missing_ok=True)
            self.logger.info("已上传并删除本地音频文件：%s", audio_file)
        return ok

    def _download_from_webdav(self, task: Task, webdav: WebDavClient) -> list[Path]:
        self.logger.info("尝试从 WebDAV 获取 %s 的音频", task.bvid)
        result: list[Path] = []

        single = self.audio_dir / f"{task.bvid}.mp3"
        if webdav.download(f"{task.bvid}.mp3", single):
            return [single]

        for index in range(1, 100):
            name = f"{task.bvid}_{index}.mp3"
            target = self.audio_dir / name
            if webdav.download(name, target):
                result.append(target)
            else:
                break
        return result

    def _download_with_ytdlp(self, task: Task) -> list[Path]:
        self.logger.info("使用 yt-dlp 下载音频：%s", task.source_url)
        output_template = self.audio_dir / f"{task.bvid}_%(playlist_index)s"
        opts = {
            "format": "ba/bestaudio",
            "outtmpl": str(output_template),
            "retries": 20,
            "continuedl": True,
            "retry_sleep": {"http": 10, "fragment": 10, "hls": 10},
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }
        cookie_file = self.config.data_dir / "userdata" / "server_bili_cookies.txt"
        if not cookie_file.exists():
            bili_txt = self.config.data_dir / "userdata" / "bili_cookies.txt"
            bili_json = self.config.data_dir / "userdata" / "bili_cookies.json"
            if bili_txt.exists():
                cookie_file = bili_txt
            elif bili_json.exists():
                try:
                    self._export_json_to_netscape_cookies(bili_json, bili_txt)
                    cookie_file = bili_txt
                except Exception as exc:
                    self.logger.warning("将 bili_cookies.json 转换为 Netscape 格式失败：%s", exc)

        if cookie_file.exists():
            opts["cookiefile"] = str(cookie_file)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([task.source_url])
        except Exception as exc:
            raise AudioError(f"yt-dlp 下载失败: {exc}") from exc

        na_file = self.audio_dir / f"{task.bvid}_NA.mp3"
        single = self.audio_dir / f"{task.bvid}.mp3"
        if na_file.exists():
            na_file.rename(single)
            return [single]

        files = sorted(self.audio_dir.glob(f"{task.bvid}_*.mp3"))
        if files:
            return files
        if single.exists():
            return [single]
        raise AudioError(f"yt-dlp 已完成，但在 {task.bvid} 中未找到任何音频文件")

    def _clean_task_audio(self, task: Task) -> None:
        for path in self.audio_dir.glob(f"{task.bvid}*.mp3*"):
            path.unlink(missing_ok=True)

    def _export_json_to_netscape_cookies(self, json_path: Path, txt_path: Path) -> None:
        import json
        import http.cookiejar
        import time
        cookies_dict = json.loads(json_path.read_text(encoding="utf-8"))
        jar = http.cookiejar.MozillaCookieJar(str(txt_path))
        for name, value in cookies_dict.items():
            cookie = http.cookiejar.Cookie(
                version=0,
                name=name,
                value=value,
                port=None,
                port_specified=False,
                domain=".bilibili.com",
                domain_initial_dot=True,
                domain_specified=True,
                path="/",
                path_specified=True,
                secure=False,
                expires=int(time.time()) + 30 * 86400,
                discard=False,
                comment=None,
                comment_url=None,
                rest={"HttpOnly": None},
                rfc2109=False
            )
            jar.set_cookie(cookie)
        txt_path.parent.mkdir(parents=True, exist_ok=True)
        jar.save(ignore_discard=True, ignore_expires=True)
        self.logger.info("已将 JSON 格式 Cookie 导出为 Netscape 格式：%s", txt_path)
