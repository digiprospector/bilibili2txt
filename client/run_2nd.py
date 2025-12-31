import argparse

from out_queue import out_queue
from push_data_repo import push_data_repo
from generate_md import create_markdown_files_from_text
from sync_to_netdisk import sync_to_netdisk
from push_data_repo import push_data_repo
from openai_chat import test_openai_api

def main():
    parser = argparse.ArgumentParser(
        description="运行客户端的第二阶段任务，包括处理队列、生成Markdown和同步到网盘。",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "-f", "--force", action="store_true",
        help="强制覆盖现有文件，而不是跳过。"
    )
    args = parser.parse_args()
    force = args.force

    if not test_openai_api():
        print("AI工作不正常,退出")
        exit(-1)
    out_queue(force)
    push_data_repo()
    create_markdown_files_from_text(force)
    sync_to_netdisk()
    push_data_repo()


if __name__ == "__main__":
    main()