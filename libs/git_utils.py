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
            return False

        # 先处理删除
        if deleted_files:
            repo.index.remove(deleted_files, working_tree=True)
        # 再处理新增/修改和未跟踪文件
        files_to_add = added_or_modified_files + untracked_files
        if files_to_add:
            repo.index.add(files_to_add)

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
    
def reset_action_and_sync(repo_path: Path, action):
    while True:
        try:
            # Initialize GitPython repository object
            repo = git.Repo(repo_path)
            origin = repo.remotes.origin

            # 1. Sync git repo
            logger.info("正在重置并同步仓库...")
            branch_name = repo.active_branch.name

            repo.git.fetch('--all', prune=True)
            repo.git.reset('--hard', f'origin/{branch_name}')
            repo.git.clean('-fd')
            origin.pull()
            logger.info("仓库已成功重置并与远程同步。")
            

            # 2. Move files from partitions to ../queue/to_stt
            commit_message = action()
            if commit_message == "无文件可添加":
                logger.info("没有文件需要添加，跳过提交步骤。")
                break

            # 3. Commit changes
            logger.info("正在添加、提交和推送更改...")
            obj_to_add = [item.a_path for item in repo.index.diff(None)] + repo.untracked_files
            repo.index.add(obj_to_add)
            repo.index.commit(commit_message)
            # 4. Push changes
            logger.info("正在推送更改...")
            push_infos = origin.push()

            push_failed = any(info.flags & (git.PushInfo.ERROR | git.PushInfo.REJECTED) for info in push_infos)

            if not push_failed:
                logger.info("文件复制并推送成功。")
                break  # Success, exit the while loop
            else:
                for info in push_infos:
                    if info.flags & (git.PushInfo.ERROR | git.PushInfo.REJECTED):
                        logger.error(f"推送失败详情: {info.summary}")
                logger.error("推送失败，将在5秒后重试...")
                time.sleep(5)

        except GitCommandError as e:
            logger.error(f"发生Git操作错误: {e}。将在5秒后重试...")
            time.sleep(5)
        except Exception as e:
            logger.error(f"发生未知错误: {e}。将在5秒后重试...")
            time.sleep(5)