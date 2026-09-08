from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path

import git

_local = threading.local()


def install_git_timeout_patch() -> None:
    """在 Windows 下为 GitPython 启用进程级超时控制（kill_after_timeout）。

    GitPython 原生在 Windows 上禁用了 kill_after_timeout，遇到网络挂起会无限阻塞。
    本补丁通过 Windows 的 taskkill /F /T 终止超时进程树。
    """
    if sys.platform != "win32" or getattr(git.cmd.Git, "_timeout_patched", False):
        return

    orig_execute = git.cmd.Git.execute
    orig_safer_popen = git.cmd.safer_popen

    def custom_safer_popen(*p_args, **p_kwargs):
        proc = orig_safer_popen(*p_args, **p_kwargs)
        setup_fn = getattr(_local, "watchdog_setup", None)
        if setup_fn:
            setup_fn(proc)
        return proc

    git.cmd.safer_popen = custom_safer_popen

    def patched_execute(self, command, *args, **kwargs):
        kill_after_timeout = kwargs.get("kill_after_timeout")
        if kill_after_timeout is not None:
            kwargs["kill_after_timeout"] = None
            timeout = float(kill_after_timeout)

            watchdog = None
            kill_check = threading.Event()

            def watchdog_setup(proc):
                nonlocal watchdog

                def kill_proc_tree(pid: int) -> None:
                    try:
                        kill_check.set()
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(pid)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=False,
                        )
                    except Exception:
                        pass

                watchdog = threading.Timer(timeout, kill_proc_tree, args=(proc.pid,))
                watchdog.daemon = True
                watchdog.start()

            _local.watchdog_setup = watchdog_setup
            try:
                try:
                    result = orig_execute(self, command, *args, **kwargs)
                except git.GitCommandError:
                    if kill_check.is_set():
                        raise git.GitCommandError(
                            command,
                            f'Timeout: Git 命令在 {timeout} 秒内未完成，已强制终止。',
                        ) from None
                    raise
                if kill_check.is_set():
                    raise git.GitCommandError(
                        command,
                        f'Timeout: Git 命令在 {timeout} 秒内未完成，已强制终止。',
                    )
                return result
            finally:
                _local.watchdog_setup = None
                if watchdog:
                    watchdog.cancel()

        return orig_execute(self, command, *args, **kwargs)

    git.cmd.Git.execute = patched_execute
    git.cmd.Git._timeout_patched = True


install_git_timeout_patch()


def open_repo(repo_dir: Path, error_cls: type[Exception] = RuntimeError) -> git.Repo:
    try:
        return git.Repo(repo_dir)
    except Exception as exc:
        raise error_cls(f"Not a Git repository: {repo_dir}") from exc


def commit_all(repo: git.Repo, message: str, logger: logging.Logger) -> bool:
    repo.git.add(A=True)
    if not repo.is_dirty(untracked_files=True):
        logger.info("%s 中没有需要提交的更改", repo.working_dir)
        return False
    repo.index.commit(message)
    logger.info("已提交：%s", message)
    return True


def push_and_check(origin, error_cls: type[Exception] = RuntimeError, kill_after_timeout: float | None = None) -> None:
    push_infos = origin.push(kill_after_timeout=kill_after_timeout)
    failures = [
        info.summary
        for info in push_infos
        if info.flags & (git.PushInfo.ERROR | git.PushInfo.REJECTED)
    ]
    if failures:
        raise error_cls(f"Push failed: {'; '.join(failures)}")


def push_and_set_upstream(repo: git.Repo, remote_name: str = "origin", branch_name: str = "main", error_cls: type[Exception] = RuntimeError) -> None:
    try:
        remote = getattr(repo.remotes, remote_name)
    except AttributeError as exc:
        raise error_cls(f"Missing remote: {remote_name}") from exc

    try:
        current_branch = repo.active_branch.name
    except TypeError as exc:
        raise error_cls("Repository is in detached HEAD state") from exc

    push_infos = remote.push(refspec=f"{current_branch}:{branch_name}", set_upstream=True)
    failures = [
        info.summary
        for info in push_infos
        if info.flags & (git.PushInfo.ERROR | git.PushInfo.REJECTED)
    ]
    if failures:
        raise error_cls(f"Push failed: {'; '.join(failures)}")
