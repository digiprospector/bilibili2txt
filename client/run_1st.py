import argparse

from scrape import scrape
from in_queue import in_queue
from local_download_and_upload_to_webdav import local_download_and_upload_to_webdav

def main(up_mid=None):
    new_videos_list_file = scrape(target_up_mid=up_mid)
    if new_videos_list_file:
        in_queue(new_videos_list_file)
        local_download_and_upload_to_webdav()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="抓取Bilibili视频并处理。")
    parser.add_argument(
        "-u", "--up-mid",
        type=int,
        default=None,
        help="指定要抓取的单个UP主的MID。"
    )
    args = parser.parse_args()
    main(up_mid=args.up_mid)