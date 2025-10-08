from scrape import scrape
from client_in_queue import in_queue
from client_local_download_and_upload_to_webdav import local_download_and_upload_to_webdav

def main():
    scrape()
    in_queue()
    local_download_and_upload_to_webdav()

if __name__ == "__main__":
    main()