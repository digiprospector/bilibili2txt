from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))
from dp_logging import setup_logger
from server_out_queue import out_queue, set_logger as server_out_queue_set_logger
from server_in_queue import in_queue
from process_input import process_input

logger = setup_logger(Path(__file__).stem)
server_out_queue_set_logger(logger)

def main():
    count = 0
    while True:
        any_input_file = out_queue()
        if not any_input_file:
            logger.info("没有检测到新的要处理的视频，退出.")
            break
        
        process_input()
        count += 1
        if count >= 3:
            logger.info("已处理3轮，退出.")
            break
    in_queue()

if __name__ == "__main__":
    main()