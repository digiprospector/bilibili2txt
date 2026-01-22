import sys
from pathlib import Path

# 获取项目根目录 (client 的上一级)
CLIENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CLIENT_DIR.parent
COMMON_DIR = ROOT_DIR / "common"
LIBS_DIR = ROOT_DIR / "libs"

# 确保 common 和 libs 在 sys.path 中
for d in [COMMON_DIR, LIBS_DIR]:
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))

# 导入环境配置
try:
    from env import config, setup_logger, get_path
except ImportError:
    print(f"Error: Could not import 'env' from {COMMON_DIR}")
    sys.exit(1)

def get_standard_logger(filename):
    """为脚本创建一个标准的日志对象"""
    return setup_logger(Path(filename).stem, log_dir=ROOT_DIR / "logs")

__all__ = ['config', 'setup_logger', 'get_path', 'get_standard_logger', 'ROOT_DIR']
