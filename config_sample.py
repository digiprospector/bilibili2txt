from pathlib import Path

config = {
    # ============== 目录配置 ==============
    "data_dir": "data",  # data目录，用于保存记录
    "userdata_dir": "data/userdata",  # 保存用户数据，包括数据库文件和cookies
    "save_text_dir": "data/save",  # 保存server处理好的文本文件
    "temp_dir": "temp",  # 临时目录
    "queue_dir": "queue",  # queue目录，是一个git仓库，用来和服务器交换文件
    "new_video_list_dir": "temp/new_video_list",  # 临时目录，用来保存抓取到的新视频列表
    "save_new_video_list_dir": "data/new_video_list",  # 保存已经处理过的新视频列表
    
    # ============== Bilibili 配置 ==============
    "target_group": ["默认分组"],  # bilibili中的分组，分组中的up主会被遍历
    "request_interval": 3,  # 请求间隔（秒），太小了容易出412风控
    "debug": False,
    
    # ============== 服务器端配置 ==============
    "server_faster_whisper_path": "/content/drive/MyDrive/Faster-Whisper-XXL/faster-whisper-xxl",  # 服务器端faster whisper xxl的目录
    "server_out_queue_duration_limit": 864000,  # 服务器端处理视频时长限制，单位秒，默认10天
    "server_out_queue_limit_type": "less_than",  # less_than: 只处理小于时长的视频, better_greater_than: 优先处理大于时长的视频
    
    # ============== 网盘同步配置 ==============
    "netdisk_dir": Path("/path/to/your/netdisk"),  # 处理完成的markdown文件，放到网盘里自动同步
    
    # ============== WebDAV 配置 ==============
    # 腾讯云下载不了bilibili视频，本地下载后传到webdav，服务器再去下载
    # 推荐免费的 infini-cloud，15G空间，正好用于中转
    "webdav_url": "https://your-webdav-server.com/dav/",
    "webdav_username": "your_webdav_username",
    "webdav_password": "your_webdav_password",
    # "webdav_proxy": "http://127.0.0.1:7897",  # 上传webdav时使用的代理（可选）
    "local_download_audio_seconds": 1,  # 大于这个时长（秒）的视频才会本地下载再上传到webdav
    
    # ============== AI 配置 ==============
    "select_open_ai": "example",  # 默认使用的 AI 名称
    "open_ai_list": [
        {
            "openai_api_name": "example",  # AI 配置名称，用于标识
            "openai_api_key": "sk-your-api-key-here",  # API Key
            "openai_base_url": "https://api.openai.com/v1",  # API Base URL
            "openai_model": "gpt-3.5-turbo",  # 使用的模型
            "interval": "12"  # 请求间隔（秒），避免触发频率限制
        },
        # 可以添加多个 AI 配置，程序会并行使用
        # {
        #     "openai_api_name": "another_ai",
        #     "openai_api_key": "sk-another-api-key",
        #     "openai_base_url": "https://another-api.com/v1",
        #     "openai_model": "gpt-4",
        #     "interval": "10"
        # }
    ]
}
