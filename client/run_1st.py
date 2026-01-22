from scrape import scrape
from in_queue import in_queue
from local_download_and_upload_to_webdav import local_download_and_upload_to_webdav

def main():
    new_videos_list_file = scrape()
    if new_videos_list_file:
        in_queue(new_videos_list_file)
        local_download_and_upload_to_webdav()

if __name__ == "__main__":
    main()