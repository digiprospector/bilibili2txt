config = {
    "userdata_dir": "data/userdata",
    "temp_dir": "temp",
    "queue_dir": "queue",
    "new_video_list_dir": "temp/new_video_list",
    "save_new_video_list_dir": "data/new_video_list",
    "target_group": ["默认分组"],
    "request_interval": 3, #请求间隔,太小了容易出412风控
    "debug": False,
    "server_faster_whisper_path": '/content/drive/MyDrive/Faster-Whisper-XXL/faster-whisper-xxl',
    "server_out_queue_duration_limit": 864000, #服务器端处理视频时长限制，单位秒，默认10天
    "server_out_queue_limit_type": "less_than", #服务器端处理视频时长
    "save_text_dir": "data/save",
    "netdisk_dir": "/directory/netdisk/sync"
}
