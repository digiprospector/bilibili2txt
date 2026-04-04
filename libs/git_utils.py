#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Git 工具模块 - 统一管理 Git 仓库操作

提供常用的 Git 操作封装：
- 仓库重置与同步
- 提交与推送
- 事务式操作模式
"""

import time
from pathlib import Path
from typing import Callable, Optional

import git
from git.exc import GitCommandError

from env import setup_logger

# 默认日志
SCRIPT_DIR = Path(__file__).parent
_logger = setup_logger(Path(__file__).stem, log_dir=SCRIPT_DIR.parent / "logs")

# 分块大小，避免命令行过长
CHUNK_SIZE = 100


def set_logger(logger_instance) -> None:
    """设置自定义 logger"""
    global _logger
    _logger = logger_instance


def reset_repo(repo_path: Path) -> None:
    """
    重置仓库并与远程同步
    
    Args:
        repo_path: 仓库路径
        
    Raises:
        GitCommandError: Git 操作失败
    """
    try:
        repo = git.Repo(repo_path)
        origin = repo.remotes.origin
        branch_name = repo.active_branch.name

        _logger.info("正在重置并同步仓库...")
        repo.git.fetch('--all', prune=True)
        repo.git.reset('--hard', f'origin/{branch_name}')
        repo.git.clean('-fd')
        # 确保本地分支追踪远程分支（orphan 重置后 upstream 可能丢失）
        repo.git.branch('--set-upstream-to', f'origin/{branch_name}', branch_name)
        origin.pull()
        _logger.info("仓库已成功重置并与远程同步。")
        
    except GitCommandError as e:
        _logger.error(f"发生 Git 操作错误: {e}")
        raise
    except Exception as e:
        _logger.error(f"发生未知错误: {e}")
        raise


def _get_file_changes(repo: git.Repo) -> tuple[list[str], list[str], list[str]]:
    """获取仓库中的文件变更"""
    diff_items = repo.index.diff(None)
    deleted = [item.a_path for item in diff_items if item.change_type == 'D']
    modified = [item.a_path for item in diff_items if item.change_type in ('A', 'M')]
    untracked = list(repo.untracked_files)
    return deleted, modified, untracked


def _process_in_chunks(items: list[str], action: Callable, action_name: str) -> None:
    """分块处理文件列表"""
    if not items:
        return
    _logger.info(f"正在分批{action_name} {len(items)} 个文件...")
    for i in range(0, len(items), CHUNK_SIZE):
        action(items[i:i + CHUNK_SIZE])


def push_changes(repo_path: Path, commit_message: str) -> bool:
    """
    添加、提交并推送更改
    
    Args:
        repo_path: 仓库路径
        commit_message: 提交信息
        
    Returns:
        推送是否成功
        
    Raises:
        GitCommandError: Git 操作失败
    """
    try:
        repo = git.Repo(repo_path)
        origin = repo.remotes.origin
        
        _logger.info("正在添加、提交和推送更改...")
        
        deleted, modified, untracked = _get_file_changes(repo)
        
        if not (deleted or modified or untracked):
            _logger.info("没有文件需要添加，跳过提交步骤。")
            return True

        # 处理删除的文件
        _process_in_chunks(
            deleted, 
            lambda chunk: repo.index.remove(chunk, working_tree=True),
            "移除"
        )
        
        # 处理新增/修改的文件
        _process_in_chunks(
            modified + untracked,
            lambda chunk: repo.index.add(chunk),
            "添加"
        )

        repo.index.commit(commit_message)
        _logger.info("正在推送更改...")
        
        push_infos = origin.push()
        push_failed = any(
            info.flags & (git.PushInfo.ERROR | git.PushInfo.REJECTED) 
            for info in push_infos
        )

        if not push_failed:
            _logger.info("更改已成功推送。")
            return True
        
        for info in push_infos:
            if info.flags & (git.PushInfo.ERROR | git.PushInfo.REJECTED):
                _logger.error(f"推送失败详情: {info.summary}")
        return False
        
    except GitCommandError as e:
        _logger.error(f"发生 Git 操作错误: {e}")
        raise
    except Exception as e:
        _logger.error(f"发生未知错误: {e}")
        raise


def git_repo_transaction(
    repo_path: Path, 
    action_func: Callable[[], Optional[str]], 
    success_func: Optional[Callable[[str], None]] = None, 
    retry_interval: int = 10
) -> bool:
    """
    统一的 Git 仓库事务处理：重置 -> 执行操作 -> 提交推送
    
    Args:
        repo_path: 仓库路径
        action_func: 核心操作函数。返回 commit_message 表示需要推送；返回 None 表示无操作
        success_func: 推送成功后的回调函数，接收 commit_message 作为参数
        retry_interval: 失败重试间隔（秒）
        
    Returns:
        操作是否成功
    """
    while True:
        try:
            # 1. 重置并拉取最新代码
            reset_repo(repo_path)
            
            # 2. 执行业务逻辑
            commit_msg = action_func()
            if not commit_msg:
                return True
            
            # 3. 提交并推送
            if push_changes(repo_path, commit_msg):
                # 4. 成功后的回调
                if success_func:
                    success_func(commit_msg)
                return True
            
            _logger.error(f"推送失败，{retry_interval}秒后重试...")
            time.sleep(retry_interval)
            
        except Exception as e:
            _logger.error(f"Git 事务执行失败: {e}")
            _logger.info(f"{retry_interval}秒后重试...")
            time.sleep(retry_interval)


def shrink_repo_if_empty(repo_path: Path, dirs_to_check: list[str]) -> bool:
    """
    检查指定目录是否都为空，如果为空，则删除 Git 仓库的历史记录，
    并重新提交以减小仓库体积，同时保留指定的目录。
    """
    # 检查是否全部为空
    for d in dirs_to_check:
        d_path = repo_path / d
        if not d_path.exists():
            continue
        # 排除 . 隐藏文件
        has_files = False
        for f in d_path.iterdir():
            if not f.name.startswith('.'):
                has_files = True
                break
        if has_files:
            _logger.info(f"目录 {d} 非空，跳过仓库清理。")
            return False
            
    _logger.info("指定目录均为空，准备清理仓库历史记录...")
    try:
        repo = git.Repo(repo_path)
        active_branch = repo.active_branch.name
        
        # 确保指定目录有 .gitkeep，否则 git 不会跟踪空目录
        for d in dirs_to_check:
            d_path = repo_path / d
            d_path.mkdir(parents=True, exist_ok=True)
            keep_file = d_path / ".gitkeep"
            if not keep_file.exists():
                keep_file.touch()
        
        # 执行 orphan branch 逻辑
        temp_branch = f"temp_orphan_{int(time.time())}"
        repo.git.checkout('--orphan', temp_branch)
        repo.git.add('-A')
        repo.git.commit('-m', 'Reset repository history to shrink size')
        repo.git.branch('-D', active_branch)
        repo.git.branch('-m', active_branch)
        
        _logger.info("正在强制推送到远程仓库...")
        repo.git.push('-f', 'origin', active_branch)
        
        # 清理无用的 git 对象
        repo.git.gc('--prune=now')
        
        _logger.info("仓库历史记录已清理完成。")
        return True
    except GitCommandError as e:
        _logger.error(f"发生 Git 操作错误: {e}")
        return False
    except Exception as e:
        _logger.error(f"清理仓库历史记录失败: {e}")
        return False
