from pathlib import Path
import git
from git.exc import GitCommandError
import time
from dp_logging import setup_logger

SCRIPT_DIR = Path(__file__).parent
logger = setup_logger(Path(__file__).stem, log_dir=SCRIPT_DIR.parent / "logs")

def set_logger(logger_instance):
    global logger
    logger = logger_instance

def reset_repo(repo_path: Path):
    try:
        repo = git.Repo(repo_path)
        origin = repo.remotes.origin

        logger.info("正在重置并同步仓库...")
        branch_name = repo.active_branch.name

        repo.git.fetch('--all', prune=True)
        repo.git.reset('--hard', f'origin/{branch_name}')
        repo.git.clean('-fd')
        origin.pull()
        logger.info("仓库已成功重置并与远程同步。")
    except GitCommandError as e:
        logger.error(f"发生Git操作错误: {e}")
        raise
    except Exception as e:
        logger.error(f"发生未知错误: {e}")
        raise

def push_changes(repo_path: Path, commit_message: str):
    try:
        repo = git.Repo(repo_path)
        origin = repo.remotes.origin
        logger.info("正在添加、提交和推送更改...")
        # 处理删除和新增/修改的文件
        diff_items = repo.index.diff(None)
        deleted_files = [item.a_path for item in diff_items if item.change_type == 'D']
        added_or_modified_files = [item.a_path for item in diff_items if item.change_type in ('A', 'M')]
        untracked_files = repo.untracked_files

        if not (deleted_files or added_or_modified_files or untracked_files):
            logger.info("没有文件需要添加，跳过提交步骤。")
            return True

        # 先处理删除
        CHUNK_SIZE = 100  # 定义一个安全的分块大小以避免命令行过长错误
        if deleted_files:
            logger.info(f"正在从索引中分批移除 {len(deleted_files)} 个已删除文件...")
            for i in range(0, len(deleted_files), CHUNK_SIZE):
                chunk = deleted_files[i:i + CHUNK_SIZE]
                repo.index.remove(chunk, working_tree=True)
        # 再处理新增/修改和未跟踪文件
        files_to_add = added_or_modified_files + untracked_files
        if files_to_add:
            logger.info(f"正在分批添加 {len(files_to_add)} 个新增/修改/未跟踪的文件...")
            for i in range(0, len(files_to_add), CHUNK_SIZE):
                chunk = files_to_add[i:i + CHUNK_SIZE]
                repo.index.add(chunk)

        repo.index.commit(commit_message)
        logger.info("正在推送更改...")
        push_infos = origin.push()

        push_failed = any(info.flags & (git.PushInfo.ERROR | git.PushInfo.REJECTED) for info in push_infos)

        if not push_failed:
            logger.info("更改已成功推送。")
            return True
        else:
            for info in push_infos:
                if info.flags & (git.PushInfo.ERROR | git.PushInfo.REJECTED):
                    logger.error(f"推送失败详情: {info.summary}")
            return False
    except GitCommandError as e:
        logger.error(f"发生Git操作错误: {e}")
        raise
    except Exception as e:
        logger.error(f"发生未知错误: {e}")
        raise
    
def git_repo_transaction(repo_path: Path, action_func, success_func=None, retry_interval: int = 10):
    """
    统一的 Git 仓库事务处理：重置 -> 执行操作 -> 提交推送
    :param repo_path: 仓库路径
    :param action_func: 核心操作函数。返回 commit_message (str) 表示需要推送；返回 None 表示无操作。
    :param success_func: 推送成功后的回调函数。接收 action_func 的返回值。
    :param retry_interval: 失败重试间隔（秒）
    """
    while True:
        try:
            # 1. 重置并拉取最新代码
            reset_repo(repo_path)
            
            # 2. 执行业务逻辑
            commit_msg = action_func()
            if not commit_msg:
                # logger.info("无需推送，结束事务。")
                return True
            
            # 3. 提交并推送
            if push_changes(repo_path, commit_msg):
                # 4. 成功后的回调
                if success_func:
                    success_func(commit_msg)
                return True
            else:
                logger.error(f"推送失败，{retry_interval}秒后重试...")
                time.sleep(retry_interval)
        except Exception as e:
            logger.error(f"Git 事务执行失败: {e}")
            time.sleep(retry_interval)
            logger.info(f"{retry_interval}秒后重试...")
