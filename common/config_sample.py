from pathlib import Path

config = {
    "data_dir": "data",
    "userdata_dir": "data/userdata", #保存用户数据,包括数据库文件和cookies
    "temp_dir": "temp",
    "queue_dir": "queue", #queue目录,是一个git仓库,用来和服务器交换文件
    "new_video_list_dir": "temp/new_video_list", #临时目录,用来保存抓取到的新视频列表,在列表成功上传到queue里,会移动到save_new_video_list_dir目录保存
    "save_new_video_list_dir": "data/new_video_list", #保存已经处理过的新视频列表
    "target_group": ["默认分组"],
    "request_interval": 3, #请求间隔,太小了容易出412风控
    "debug": False,
    "server_faster_whisper_path": '/content/drive/MyDrive/Faster-Whisper-XXL/faster-whisper-xxl',
    "server_out_queue_duration_limit": 864000, #服务器端处理视频时长限制，单位秒，默认10天
    "server_out_queue_limit_type": "less_than", #服务器端处理视频时长
    "save_text_dir": "data/save",
    "netdisk_dir": Path("/directory/netdisk/sync"),
    "webdav_url": "https://webdav.infini-cloud.net/dav/",
    "webdav_username": "webdav_username",
    "webdav_password": "webdav_password",
    #"webdav_proxy": "http://127.0.0.1:7897",
    "local_download_audio_seconds": 1
}
