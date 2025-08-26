from pathlib import Path
import sys
import shutil
import time


SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))
from dp_logging import setup_logger
from git_utils import reset_repo, push_changes, set_logger as git_utils_set_logger

# 日志
logger = setup_logger(Path(__file__).stem, log_dir=SCRIPT_DIR.parent / "logs")
git_utils_set_logger(logger)

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

def get_dir_in_config(key: str) -> Path:
    dir_path_str = config[key]
    if dir_path_str.startswith("/"):
        dir_path = Path(dir_path_str)
    else:
        dir_path = SCRIPT_DIR.parent / dir_path_str
    logger.debug(f"config[{key}] 的路径: {dir_path}")
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path

from config import config
DATA_DIR = get_dir_in_config("data_dir")

def push_data_repo():
    push_changes(DATA_DIR, "update")
    
if __name__ == "__main__":
    push_data_repo()