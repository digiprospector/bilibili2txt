#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bilibili API 客户端模块

提供 Bilibili 网站的 API 封装：
- 二维码登录
- 关注分组管理
- 视频信息获取
- 文件下载（支持断点续传）
"""

import hashlib
import json
import logging
import time
import urllib.parse
from functools import reduce
from pathlib import Path
from typing import Optional, Union

import qrcode
import requests
from tqdm import tqdm

from env import config, setup_logger, get_path

# 模块级 logger
SCRIPT_DIR = Path(__file__).resolve().parent
logger = setup_logger(Path(__file__).stem, log_dir=SCRIPT_DIR.parent / "logs")

# WBI 签名用的混淆表
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52
]

# 视频状态错误码映射
VIDEO_ERROR_CODES = {
    "-400": "请求错误",
    "-403": "请求错误",
    "-404": "无视频",
    "62002": "稿件不可见",
    "62004": "稿件审核中",
    "62012": "仅UP主自己可见",
}

# 默认 User-Agent
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class DpBilibili:
    """Bilibili API 客户端"""
    
    def __init__(
        self,
        ua: str = DEFAULT_UA,
        cookies: Optional[dict] = None,
        logger: Optional[logging.Logger] = None,
        retry_max: int = 10,
        retry_interval: int = 5,
        userdata_dir: Optional[Path] = None
    ):
        """
        初始化 Bilibili API 客户端
        
        Args:
            ua: User-Agent 字符串
            cookies: 用于会话的 cookies
            logger: 日志记录器实例
            retry_max: API 请求失败时的最大重试次数
            retry_interval: 每次重试之间的间隔时间（秒）
            userdata_dir: 用户数据目录
        """
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': ua})
        if cookies:
            self.session.cookies.update(cookies)
        
        self.logger = logger or self._get_default_logger()
        self.retry_max = retry_max
        self.retry_interval = retry_interval
        self.request_interval = config.get('request_interval', 1)
        self.last_request_time = 0
        
        # WBI 密钥
        self.img_key: Optional[str] = None
        self.sub_key: Optional[str] = None
        
        # 用户信息
        self.mid = 0
        self.name = ""
        self.groups: dict = {}
        
        # 用户数据目录
        self.userdata_dir = userdata_dir or self._get_userdata_dir()
        
        # 初始化时获取 WBI 密钥
        self.get_wbi_keys()

    @staticmethod
    def _get_default_logger() -> logging.Logger:
        """获取默认 logger"""
        default_logger = logging.getLogger(__name__)
        if not default_logger.handlers:
            logging.basicConfig(level=logging.INFO)
        return default_logger

    @staticmethod
    def _get_userdata_dir() -> Path:
        """获取用户数据目录"""
        try:
            return get_path("userdata_dir")
        except Exception:
            return Path("data/userdata")

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """带有延迟控制的请求包装"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.request_interval:
            time.sleep(self.request_interval - elapsed)
        
        response = self.session.request(method, url, **kwargs)
        self.last_request_time = time.time()
        return response

    def _retry_request(
        self, 
        operation_name: str,
        request_func,
        error_return_value=None
    ):
        """
        带重试的请求执行
        
        Args:
            operation_name: 操作名称（用于日志）
            request_func: 请求函数，成功时返回结果，失败时抛出异常
            error_return_value: 所有重试失败后返回的值
        """
        for attempt in range(self.retry_max):
            try:
                return request_func()
            except Exception as e:
                self.logger.warning(f"{operation_name}失败 (尝试 {attempt + 1}/{self.retry_max}): {e}")
                if attempt < self.retry_max - 1:
                    self.logger.info(f"将在 {self.retry_interval} 秒后重试...")
                    time.sleep(self.retry_interval)
                else:
                    self.logger.error(f"已达到最大重试次数，{operation_name}失败。")
        return error_return_value

    # ============== 登录相关 ==============

    def login_by_qrcode(self) -> bool:
        """
        通过二维码扫描进行登录
        
        Returns:
            登录成功返回 True，否则返回 False
        """
        login_url_api = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"

        try:
            response = self._request("GET", login_url_api)
            response.raise_for_status()
            data = response.json()['data']
            qrcode_key = data['qrcode_key']
            qr_url = data['url']
        except Exception as e:
            self.logger.error(f"获取登录二维码失败: {e}")
            return False

        # 显示二维码
        qr = qrcode.QRCode()
        qr.add_data(qr_url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
        self.logger.info("请使用 Bilibili 手机客户端扫描上方二维码")

        # 轮询登录状态
        poll_api = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
        
        try:
            while True:
                time.sleep(3)
                params = {'qrcode_key': qrcode_key}
                poll_response = self._request("GET", poll_api, params=self.sign_params(params))
                poll_response.raise_for_status()
                poll_data = poll_response.json()['data']
                
                code = poll_data['code']
                if code == 0:
                    self.logger.info("登录成功！")
                    return True
                elif code == 86038:
                    self.logger.warning("二维码已失效，请重新运行程序。")
                    return False
                elif code == 86090:
                    self.logger.info("二维码已扫描，请在手机上确认登录...")
        except Exception as e:
            self.logger.error(f"轮询登录状态时发生错误: {e}")
            return False

    def login(self) -> bool:
        """
        确保用户已登录
        
        首先测试当前 session 是否有效，如果无效则调用二维码登录。
        
        Returns:
            登录成功返回 True，否则返回 False
        """
        if self.test_login():
            self.logger.info("已经登录，无需扫码登录")
            return True
        
        self.logger.info("请重新扫码登录")
        if self.login_by_qrcode() and self.test_login():
            self.logger.info("登录成功")
            return True
        
        self.logger.error("登录失败，请检查二维码或网络连接")
        return False

    def test_login(self) -> bool:
        """
        测试当前 session 中的 cookies 是否有效
        
        Returns:
            已登录返回 True，否则返回 False
        """
        nav_api = "https://api.bilibili.com/x/web-interface/nav"
        try:
            response = self._request("GET", nav_api)
            response.raise_for_status()
            data = response.json().get('data', {})
            if data.get('isLogin'):
                self.mid = data.get('mid', 0)
                self.name = data.get('uname', "")
                self.logger.info(f"已经登录 {self.name} (mid: {self.mid})")
                return True
            return False
        except Exception as e:
            self.logger.warning(f"测试登录时发生错误: {e}")
            self.groups = {}
            return False

    # ============== WBI 签名 ==============

    def get_wbi_keys(self) -> tuple[Optional[str], Optional[str]]:
        """
        获取 WBI 签名所需的 img_key 和 sub_key
        
        Returns:
            成功返回 (img_key, sub_key)，失败返回 (None, None)
        """
        url = "https://api.bilibili.com/x/web-interface/nav"

        def _fetch_keys():
            response = self._request("GET", url, timeout=10)
            response.raise_for_status()
            data = response.json()
            img_url = data["data"]["wbi_img"]["img_url"]
            sub_url = data["data"]["wbi_img"]["sub_url"]
            self.img_key = img_url.split("/")[-1].split(".")[0]
            self.sub_key = sub_url.split("/")[-1].split(".")[0]
            self.logger.debug(f"获取 WBI 密钥成功: img_key={self.img_key}, sub_key={self.sub_key}")
            return self.img_key, self.sub_key

        result = self._retry_request("获取 WBI 密钥", _fetch_keys, (None, None))
        return result if result else (None, None)

    def _get_mixin_key(self, orig: str) -> str:
        """根据 B 站规则对 imgKey 和 subKey 进行打乱，生成 mixinKey"""
        return reduce(lambda s, i: s + orig[i], MIXIN_KEY_ENC_TAB, '')[:32]

    def sign_params(self, params: dict) -> dict:
        """
        为请求参数进行 WBI 签名
        
        Args:
            params: 需要签名的原始参数字典
            
        Returns:
            包含 w_rid 和 wts 签名的新参数字典
        """
        if not self.img_key or not self.sub_key:
            self.logger.error("缺少 WBI 密钥，无法进行参数签名")
            return {}
        
        mixin_key = self._get_mixin_key(self.img_key + self.sub_key)
        params = dict(params)  # 复制一份
        params['wts'] = int(time.time())
        
        # 参数按 key 排序
        params = dict(sorted(params.items()))
        
        # 过滤 value 中的特殊字符
        params_filtered = {
            k: ''.join(c for c in str(v) if c not in "!'()*")
            for k, v in params.items()
        }
        query = urllib.parse.urlencode(params_filtered)
        
        # 计算签名
        w_rid = hashlib.md5((query + mixin_key).encode()).hexdigest()
        params['w_rid'] = w_rid
        return params

    # ============== 关注分组 ==============

    def get_following_groups(self) -> dict:
        """
        获取当前用户的关注分组列表
        
        Returns:
            关注分组字典 {tag_id: {'name': group_name, 'count': member_count}}
        """
        url = "https://api.bilibili.com/x/relation/tags"
        
        def _fetch():
            response = self._request("GET", url)
            response.raise_for_status()
            data = response.json()
            if data['code'] == 0:
                self.groups = {
                    group['tagid']: {'name': group['name'], 'count': group['count']} 
                    for group in data['data']
                }
                return self.groups
            raise RuntimeError(f"API 返回错误: {data['message']}")

        result = self._retry_request("获取关注分组", _fetch, {})
        return result if result else {}

    def get_ups_in_group(self, tag_id: int, pn: int = 1, ps: int = 300) -> dict:
        """
        根据分组 ID 获取关注的 UP 主列表
        
        Args:
            tag_id: 关注分组的 ID
            pn: 页码
            ps: 每页数量
            
        Returns:
            UP 主列表字典 {mid: {'name': up_name}}
        """
        api_url = "https://api.bilibili.com/x/relation/tag"
        params = {"mid": self.mid, "tagid": tag_id, "pn": pn, "ps": ps}
        headers = {"Referer": f"https://space.bilibili.com/{self.mid}/fans/follow"}

        def _fetch():
            response = self._request("GET", api_url, headers=headers, params=self.sign_params(params), timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get('code') == 0:
                return {item["mid"]: {'name': item["uname"]} for item in data.get("data", [])}
            raise RuntimeError(f"API 返回错误: {data.get('message')}")

        result = self._retry_request("获取分组关注列表", _fetch, {})
        return result if result else {}

    # ============== UP 主和视频信息 ==============

    def get_up_info(self, mid: Union[int, str]) -> dict:
        """
        获取指定 UP 主的个人信息
        
        Args:
            mid: UP 主的 UID
            
        Returns:
            UP 主信息字典 {'name': up_name}
        """
        api_url = "https://api.bilibili.com/x/space/acc/info"
        params = {"mid": mid}
        headers = {"Referer": f"https://space.bilibili.com/{mid}/"}

        def _fetch():
            response = self._request("GET", api_url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get('code') == 0:
                return {'name': data.get("data", {}).get("name")}
            raise RuntimeError(f"API 返回错误: {data.get('message')}")

        result = self._retry_request("获取 UP 主信息", _fetch, {})
        return result if result else {}

    def get_videos_in_up(self, mid: Union[int, str], ps: int = 30, pn: int = 1) -> dict:
        """
        获取指定 UP 主的视频列表
        
        Args:
            mid: UP 主的 UID
            ps: 每页视频数量
            pn: 页码
            
        Returns:
            视频列表字典 {bvid: {'title': video_title}}
        """
        params = {
            "mid": mid,
            "ps": ps,
            "pn": pn,
            "order": "pubdate",
            "platform": "web",
            "web_location": "1550101"
        }
        headers = {"Referer": f"https://space.bilibili.com/{mid}/"}

        def _fetch():
            response = self._request(
                "GET",
                "https://api.bilibili.com/x/space/wbi/arc/search",
                params=self.sign_params(params),
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            if data["code"] == 0:
                return {
                    video["bvid"]: {'title': video["title"]}
                    for video in data["data"]["list"]["vlist"]
                }
            raise RuntimeError(f"API 返回错误: code={data['code']}, msg={data['message']}")

        result = self._retry_request("获取 UP 主视频列表", _fetch, {})
        return result if result else {}

    def get_video_info(self, bvid: str) -> dict:
        """
        获取指定 BVID 视频的详细信息
        
        Args:
            bvid: 视频的 BVID
            
        Returns:
            视频信息字典 {title, up_name, pubdate, duration, cid, status}
        """
        api_url = "https://api.bilibili.com/x/web-interface/view"
        params = {"bvid": bvid}
        headers = {"Referer": "https://www.bilibili.com/video"}

        def _fetch():
            response = self._request("GET", api_url, params=self.sign_params(params), headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('code') == 0:
                video_data = data.get("data", {})
                status = 'upower' if video_data.get('is_upower_exclusive') else 'normal'
                return {
                    'title': video_data["title"],
                    'up_name': video_data["owner"]["name"],
                    'pubdate': video_data["pubdate"],
                    'duration': video_data['duration'],
                    'cid': video_data['cid'],
                    'status': status
                }
            
            # 处理错误状态
            error_msg = VIDEO_ERROR_CODES.get(str(data.get('code')), data.get('message', '未知错误'))
            self.logger.warning(f"获取视频信息失败: {error_msg}")
            return {'pubdate': 0, 'duration': 0, 'cid': 0, 'status': error_msg}

        result = self._retry_request("获取视频信息", _fetch, {})
        return result if result else {}

    # ============== 文件下载 ==============

    def download_file(self, url: str, file_path: Path) -> bool:
        """
        下载文件，支持断点续传
        
        Args:
            url: 文件的下载 URL
            file_path: 文件保存的本地路径
            
        Returns:
            下载成功返回 True，否则返回 False
        """
        headers = {"referer": 'https://www.bilibili.com'}
        max_attempts = 10
        retry_interval = 5
        
        for attempt in range(max_attempts):
            try:
                file_size = 0
                if file_path.exists():
                    file_size = file_path.stat().st_size
                    headers['Range'] = f'bytes={file_size}-'
                
                response = self._request("GET", url, headers=headers, stream=True, timeout=30)
                
                if response.status_code == 206:
                    mode = 'ab'
                elif response.status_code == 200:
                    mode = 'wb'
                    file_size = 0
                else:
                    self.logger.warning(f"服务器返回异常状态码: {response.status_code}")
                    if attempt < max_attempts - 1:
                        time.sleep(retry_interval)
                        continue
                    return False
                
                total_size = int(response.headers.get('content-length', 0))
                with open(file_path, mode) as file, tqdm(
                    desc="下载音频",
                    total=total_size + file_size,
                    unit='B',
                    unit_scale=True,
                    unit_divisor=1024,
                    initial=file_size,
                    position=0,
                    leave=True
                ) as bar:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            file.write(chunk)
                            bar.update(len(chunk))
                
                self.logger.info("下载完成!")
                return True
                
            except Exception as e:
                self.logger.warning(f"下载过程中出现错误: {e}")
                if attempt < max_attempts - 1:
                    self.logger.info(f"{retry_interval}秒后重试...")
                    time.sleep(retry_interval)
                else:
                    self.logger.error("已达到最大重试次数，下载失败。")
        
        return False


# 兼容性别名
dp_bilibili = DpBilibili


if __name__ == "__main__":
    cookies = {}
    try:
        userdata_dir = get_path("userdata_dir")
    except Exception:
        userdata_dir = Path("data/userdata")
        
    cookies_file = userdata_dir / "bili_cookies.json"
    if cookies_file.exists():
        with open(cookies_file, "r") as f:
            cookies = json.load(f)
    
    client = DpBilibili(cookies=cookies, userdata_dir=userdata_dir)
    
    if client.login():
        groups = client.get_following_groups()
        client.logger.debug(f"关注分组: {groups}")
        
        if groups:
            group_id, info = next(iter(groups.items()))
            group_name = info['name']
            
            client.logger.info(f"第一个分组: {group_name}, ID: {group_id}, UP主数量: {info['count']}")
            ups = client.get_ups_in_group(group_id)
            client.logger.info(f"分组 {group_name} 中的UP主: {ups}")
            
            if ups:
                up_id, info = next(iter(ups.items()))
                up_name = info['name']
                client.logger.info(f"第一个UP主: {up_name}, ID: {up_id}")
                
                videos = client.get_videos_in_up(up_id)
                client.logger.info(f"UP主 {up_name} 的视频列表: {videos}")
                
                if videos:
                    bvid, info = next(iter(videos.items()))
                    title = info['title']
                    client.logger.info(f"第一个视频: {title}, BV号: {bvid}")
                    
                    video_info = client.get_video_info(bvid)
                    client.logger.info(f"视频 {title} 的详细信息: {video_info}")
        else:
            client.logger.info("没有关注分组")