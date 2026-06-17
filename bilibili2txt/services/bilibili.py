from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.parse
from functools import reduce
from pathlib import Path
from typing import Any

import qrcode
import requests

from ..config import AppConfig


MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52
]

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class BilibiliService:
    def __init__(self, config: AppConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": DEFAULT_UA})
        self.request_interval = float(config.get("bilibili.request_interval", 3))
        self.last_request_at = 0.0
        self.img_key: str | None = None
        self.sub_key: str | None = None
        self.mid = 0
        self._load_cookies()
        self._get_wbi_keys()

    def login(self) -> bool:
        if self.test_login():
            self.logger.info("Bilibili 已登录")
            return True
        self.logger.info("Bilibili 需要登录，正在生成二维码")
        if self._login_by_qrcode() and self.test_login():
            self._save_cookies()
            return True
        return False

    def test_login(self) -> bool:
        try:
            response = self._request("GET", "https://api.bilibili.com/x/web-interface/nav", timeout=10)
            response.raise_for_status()
            data = response.json().get("data", {})
            if data.get("isLogin"):
                self.mid = int(data.get("mid", 0))
                self.logger.info("已登录，用户：%s (mid=%s)", data.get("uname"), self.mid)
                return True
        except Exception as exc:
            self.logger.warning("Bilibili 登录测试失败: %s", exc)
        return False

    def get_video_detail(self, bvid: str | None = None, aid: int | None = None) -> dict[str, Any]:
        params: dict[str, Any]
        if bvid:
            params = {"bvid": bvid}
        elif aid is not None:
            params = {"aid": aid}
        else:
            raise ValueError("bvid or aid is required")

        video = self._api_get(
            "https://api.bilibili.com/x/web-interface/view",
            params=self.sign_params(params),
            headers={"Referer": "https://www.bilibili.com/video"},
            timeout=10,
        )
        resolved_bvid = video["bvid"]
        return {
            "bvid": resolved_bvid,
            "aid": video.get("aid", aid),
            "title": video["title"],
            "up_name": video["owner"]["name"],
            "up_mid": video["owner"].get("mid"),
            "pubdate": video["pubdate"],
            "duration": video["duration"],
            "cid": video["cid"],
            "status": "upower" if video.get("is_upower_exclusive") else "normal",
            "source_url": f"https://www.bilibili.com/video/{resolved_bvid}",
        }

    def iter_target_videos(
        self,
        target_up_mid: int | None = None,
        groups: list[str] | None = None,
        max_pages: int = 1,
    ):
        if target_up_mid:
            up_info = self.get_up_info(target_up_mid)
            up_name = up_info.get("name", f"mid_{target_up_mid}")
            yield from self._iter_up_videos(target_up_mid, up_name, max_pages=max_pages)
            return

        groups = groups or list(self.config.get("bilibili.target_groups", []) or [])
        following_groups = self.get_following_groups()
        for group_name in groups:
            found = False
            for group_id, info in following_groups.items():
                if info.get("name") != group_name:
                    continue
                found = True
                self.logger.info("扫描群组：%s id=%s 数量=%s", group_name, group_id, info.get("count"))
                ups = self.get_ups_in_group(group_id)
                for index, (up_mid, up_info) in enumerate(ups.items(), start=1):
                    self.logger.info("扫描 UP 主 [%s/%s]：%s", index, info.get("count"), up_info.get("name"))
                    yield from self._iter_up_videos(up_mid, up_info.get("name", str(up_mid)), max_pages=max_pages)
            if not found:
                self.logger.warning("未找到配置的群组：%s", group_name)

    def get_following_groups(self) -> dict:
        data = self._api_get("https://api.bilibili.com/x/relation/tags", timeout=10)
        return {item["tagid"]: {"name": item["name"], "count": item["count"]} for item in data}

    def get_ups_in_group(self, tag_id: int, pn: int = 1, ps: int = 300) -> dict:
        params = {"mid": self.mid, "tagid": tag_id, "pn": pn, "ps": ps}
        data = self._api_get(
            "https://api.bilibili.com/x/relation/tag",
            params=self.sign_params(params),
            headers={"Referer": f"https://space.bilibili.com/{self.mid}/fans/follow"},
            timeout=10,
        )
        return {item["mid"]: {"name": item["uname"]} for item in data}

    def get_up_info(self, mid: int | str) -> dict:
        data = self._api_get(
            "https://api.bilibili.com/x/space/acc/info",
            params={"mid": mid},
            headers={"Referer": f"https://space.bilibili.com/{mid}/"},
            timeout=10,
        )
        return {"name": data.get("name")}

    def get_videos_in_up(self, mid: int | str, ps: int = 30, pn: int = 1) -> dict:
        params = {
            "mid": mid,
            "ps": ps,
            "pn": pn,
            "order": "pubdate",
            "platform": "web",
            "web_location": "1550101",
        }
        data = self._api_get(
            "https://api.bilibili.com/x/space/wbi/arc/search",
            params=self.sign_params(params),
            headers={"Referer": f"https://space.bilibili.com/{mid}/"},
            timeout=10,
        )
        return {video["bvid"]: {"title": video["title"]} for video in data["list"]["vlist"]}

    def sign_params(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.img_key or not self.sub_key:
            return params
        mixin_key = self._get_mixin_key(self.img_key + self.sub_key)
        signed = dict(params)
        signed["wts"] = int(time.time())
        signed = dict(sorted(signed.items()))
        filtered = {key: "".join(ch for ch in str(value) if ch not in "!'()*") for key, value in signed.items()}
        query = urllib.parse.urlencode(filtered)
        signed["w_rid"] = hashlib.md5((query + mixin_key).encode()).hexdigest()
        return signed

    def _iter_up_videos(self, up_mid, up_name: str, max_pages: int):
        for page in range(1, max_pages + 1):
            videos = self.get_videos_in_up(up_mid, ps=30, pn=page)
            if not videos:
                break
            for bvid, details in videos.items():
                info = {
                    "bvid": bvid,
                    "up_mid": int(up_mid),
                    "up_name": up_name,
                    "title": details.get("title", ""),
                    "source_url": f"https://www.bilibili.com/video/{bvid}",
                }
                yield info

    def _login_by_qrcode(self) -> bool:
        response = self._request("GET", "https://passport.bilibili.com/x/passport-login/web/qrcode/generate", timeout=10)
        response.raise_for_status()
        data = response.json()["data"]
        qr = qrcode.QRCode()
        qr.add_data(data["url"])
        qr.make(fit=True)
        qr.print_ascii(invert=True)
        self.logger.info("请使用 Bilibili 手机客户端扫描二维码")

        while True:
            time.sleep(3)
            poll = self._request(
                "GET",
                "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
                params={"qrcode_key": data["qrcode_key"]},
                timeout=10,
            )
            poll.raise_for_status()
            poll_data = poll.json()["data"]
            code = poll_data["code"]
            if code == 0:
                self.logger.info("Bilibili 二维码登录成功")
                return True
            if code == 86038:
                self.logger.error("Bilibili 二维码已过期")
                return False
            if code == 86090:
                self.logger.info("二维码已扫描，请在手机上确认登录")

    def _get_wbi_keys(self) -> None:
        try:
            response = self._request("GET", "https://api.bilibili.com/x/web-interface/nav", timeout=10)
            response.raise_for_status()
            data = response.json()["data"]["wbi_img"]
            self.img_key = data["img_url"].split("/")[-1].split(".")[0]
            self.sub_key = data["sub_url"].split("/")[-1].split(".")[0]
        except Exception as exc:
            self.logger.warning("获取 WBI 密钥失败，未签名的请求可能会失败: %s", exc)

    def _get_mixin_key(self, orig: str) -> str:
        return reduce(lambda result, index: result + orig[index], MIXIN_KEY_ENC_TAB, "")[:32]

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        elapsed = time.time() - self.last_request_at
        if elapsed < self.request_interval:
            time.sleep(self.request_interval - elapsed)
        response = self.session.request(method, url, **kwargs)
        self.last_request_at = time.time()
        return response

    def _api_get(self, url: str, **kwargs) -> dict[str, Any]:
        response = self._request("GET", url, **kwargs)
        response.raise_for_status()
        body = response.json()
        if body.get("code") != 0:
            raise RuntimeError(f"Bilibili API 错误: {body.get('message')}")
        return body.get("data", {})

    def _load_cookies(self) -> None:
        cookie_file = self.config.data_dir / "userdata" / "bili_cookies.json"
        if not cookie_file.exists():
            return
        try:
            self.session.cookies.update(json.loads(cookie_file.read_text(encoding="utf-8")))
            self.logger.info("已加载 Bilibili Cookie：%s", cookie_file)
        except Exception as exc:
            self.logger.warning("读取 Bilibili Cookie 文件失败 %s: %s", cookie_file, exc)

    def _save_cookies(self) -> None:
        cookie_file = self.config.data_dir / "userdata" / "bili_cookies.json"
        cookie_file.parent.mkdir(parents=True, exist_ok=True)
        cookie_file.write_text(
            json.dumps(self.session.cookies.get_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.logger.info("已保存 Bilibili Cookie：%s", cookie_file)

        try:
            netscape_file = self.config.data_dir / "userdata" / "bili_cookies.txt"
            self._export_to_netscape_cookies(netscape_file)
        except Exception as exc:
            self.logger.warning("导出 Netscape 格式 Cookie 失败: %s", exc)

    def _export_to_netscape_cookies(self, filepath: Path) -> None:
        import http.cookiejar
        jar = http.cookiejar.MozillaCookieJar(str(filepath))
        for cookie in self.session.cookies:
            # Ensure domain is correct for yt-dlp to pick up
            if not cookie.domain:
                cookie.domain = ".bilibili.com"
            jar.set_cookie(cookie)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        jar.save(ignore_discard=True, ignore_expires=True)
        self.logger.info("已导出 Netscape 格式 Cookie 到：%s", filepath)
