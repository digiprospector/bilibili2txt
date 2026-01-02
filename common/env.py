import sys
import shutil
from pathlib import Path

# Calculate paths relative to this file
COMMON_DIR = Path(__file__).resolve().parent
ROOT_DIR = COMMON_DIR.parent
LIBS_DIR = ROOT_DIR / "libs"
LOGS_DIR = ROOT_DIR / "logs"

# Ensure libs and common are in sys.path
if str(LIBS_DIR) not in sys.path:
    sys.path.append(str(LIBS_DIR))
if str(COMMON_DIR) not in sys.path:
    sys.path.append(str(COMMON_DIR))

# Now we can import dp_logging
try:
    from dp_logging import setup_logger
except ImportError:
    # Fallback if libs not found
    import logging
    def setup_logger(name, log_dir=None, **kwargs):
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(name)

# Setup Config
CONFIG_FILE = COMMON_DIR / "config.py"
CONFIG_SAMPLE_FILE = COMMON_DIR / "config_sample.py"

logger = setup_logger("env_setup", log_dir=LOGS_DIR)

if not CONFIG_FILE.exists():
    logger.info(f"Configuration file not found at {CONFIG_FILE}. Copying from sample.")
    try:
        shutil.copy(CONFIG_SAMPLE_FILE, CONFIG_FILE)
    except Exception as e:
        logger.error(f"Failed to copy configuration file: {e}")
        sys.exit(1)

try:
    from config import config
except ImportError as e:
    logger.error(f"Failed to import config: {e}")
    sys.exit(1)

def get_path(key: str, create_dir: bool = True) -> Path:
    """Resolve a path from config, handling relative/absolute paths and creating directories."""
    dir_path_str = config.get(key)
    if not dir_path_str:
        # Ideally raise error, but for compatibility maybe return None?
        # The original code crashed if key invalid or logic failed essentially.
        raise ValueError(f"Config key '{key}' not found or empty.")
    
    p = Path(dir_path_str)
    if p.is_absolute():
        dir_path = p
    else:
        dir_path = ROOT_DIR / dir_path_str

    if create_dir:
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.debug(f"Could not create directory {dir_path} (might be expected): {e}")
        
    return dir_path
