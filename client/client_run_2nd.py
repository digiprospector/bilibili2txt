from client_out_queue import out_queue
from push_data_repo import push_data_repo
from generate_md import create_markdown_files_from_text
from sync_to_netdisk import sync_to_netdisk
from push_data_repo import push_data_repo

def main():
    out_queue()
    push_data_repo()
    create_markdown_files_from_text()
    sync_to_netdisk()
    push_data_repo()


if __name__ == "__main__":
    main()