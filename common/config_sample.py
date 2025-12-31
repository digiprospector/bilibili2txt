from pathlib import Path

config = {
    # server
    "server_faster_whisper_path": '/content/drive/MyDrive/Faster-Whisper-XXL/faster-whisper-xxl', #服务器端faster whisper xxl的目录
    "server_out_queue_duration_limit": 864000, #服务器端处理视频时长限制，单位秒，默认10天
    "server_out_queue_limit_type": "less_than", #服务器端处理视频时长, less_than表示只处理小于时长的视频, better_greater_than表示优先处理大于时长的视频

    #client
    "data_dir": "data", #data目录,一个私有的github仓库,用于保存记录
    "userdata_dir": "data/userdata", #保存用户数据,包括数据库文件和cookies
    "save_text_dir": "data/save", #保存server处理好的文本文件
    "temp_dir": "temp", #临时目录,不在仓库中
    "queue_dir": "queue", #queue目录,是一个git仓库,用来和服务器交换文件
    "new_video_list_dir": "temp/new_video_list", #临时目录,用来保存抓取到的新视频列表,在列表成功上传到queue里,会移动到save_new_video_list_dir目录保存
    "save_new_video_list_dir": "data/new_video_list", #保存已经处理过的新视频列表
    "target_group": ["默认分组"], #bilibili中的分组,分组中的up主会被遍历
    "request_interval": 3, #请求间隔,太小了容易出412风控
    "debug": False,
    "netdisk_dir": Path("/directory/netdisk/sync"), #处理完成的markdown文件,放到网盘里,自动同步
    "webdav_url": "https://webdav.infini-cloud.net/dav/",#腾讯的云下载不了bilibili视频, 本地下好了以后传到webdav里,服务器再去下载,推荐免费的infini-cloud,15g空间,正好用于中转.
    "webdav_username": "webdav_username",
    "webdav_password": "webdav_password",
    #"webdav_proxy": "http://127.0.0.1:7897", #上传webdav的时候用的代理
    "local_download_audio_seconds": 1, #只有大于这个长度的才会本地下载,再上传到webdav
    "openai_api_key": "", #用AI总结需要的
    "openai_base_url": "",
    "openai_model": "gemini-3.0-pro"
}
