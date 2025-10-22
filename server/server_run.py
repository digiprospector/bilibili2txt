from pathlib import Path
import sys
import shutil

SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))
from dp_logging import setup_logger
from server_out_queue import out_queue, set_logger as server_out_queue_set_logger
from server_in_queue import in_queue, set_logger as server_in_queue_set_logger
from process_input import process_input

# 日志
logger = setup_logger(Path(__file__).stem, log_dir=SCRIPT_DIR.parent / "logs")
server_out_queue_set_logger(logger)
server_in_queue_set_logger(logger)

# 读取配置文件
CONFIG_FILE = SCRIPT_DIR.parent / "common/config.py"
CONFIG_SAMPLE_FILE = SCRIPT_DIR.parent / "common/config_sample.py"

def create_config_file():
    if not CONFIG_FILE.exists():
        logger.info(f"未找到配置文件 {CONFIG_FILE}，将从 {CONFIG_SAMPLE_FILE} 复制。")
        try:
            
            shutil.copy(CONFIG_SAMPLE_FILE, CONFIG_FILE)
        except Exception as e:
            logger.error(f"从 {CONFIG_SAMPLE_FILE} 复制配置文件失败: {e}")
            exit()
create_config_file()
from config import config
DEBUG = config["debug"]

def main():
    count = 0
    while True:
        any_input_file = out_queue(duration_limit=config.get("server_out_queue_duration_limit"), 
                                   limit_type=config.get("server_out_queue_limit_type"))
        if any_input_file == "quit":
            logger.info("检测到 quit 文件，退出任务处理循环。")
            break
        elif not any_input_file:
            logger.info("没有检测到新的要处理的视频，退出.")
            break
        
        process_input()
        count += 1
        if DEBUG and count >= 3:
            logger.info("DEBUG模式下，已处理3轮，退出.")
            break
    in_queue()

if __name__ == "__main__":
    main()