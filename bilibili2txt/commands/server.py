from __future__ import annotations

import logging
import time

from ..config import CommandContext
from ..services.gitqueue import GitQueue
from ..services.audio import AudioService
from ..services.transcriber import Transcriber


def claim(ctx: CommandContext, args, logger: logging.Logger, *, sync: bool = True) -> int:
    queue = ctx.queue(logger, sync=sync)
    server_id = ctx.server_id(args)
    max_duration = int(args.max_duration or ctx.config.get("server.max_duration_seconds", 864000))

    claimed = queue.claim_longest_task(server_id, max_duration)
    if not claimed:
        logger.info("未认领到任务")
        return 1

    path, task = claimed
    queue.commit_and_push(f"{server_id} claim {task.task_id}")
    logger.info("已认领任务 task_id=%s bvid=%s 时长=%ss 路径=%s", task.task_id, task.bvid, task.duration, path)
    return 0


def release_claimed(ctx: CommandContext, args, logger: logging.Logger, *, sync: bool = True) -> int:
    queue = ctx.queue(logger, sync=sync)
    timeout_minutes = int(args.claim_timeout_minutes or ctx.config.get("server.claim_timeout_minutes", 180))
    server_id = ctx.server_id(args)

    released = queue.release_claimed_tasks(timeout_minutes * 60, target_server_id=server_id)
    if released:
        queue.commit_and_push(f"release {released} claimed task(s) for {server_id}")
    logger.info("已释放节点 %s 超时过期的占有任务数：%s", server_id, released)
    return 0


def transcribe(ctx: CommandContext, args, logger: logging.Logger) -> int:
    queue = GitQueue(ctx.config.queue_dir, logger)
    server_id = ctx.server_id(args)
    claimed = queue.find_claimed_task(server_id)
    if not claimed:
        logger.info("节点 %s 没有已认领的任务", server_id)
        return 1

    claimed_path, task = claimed
    if task.status != "normal":
        task.last_error = f"status is not normal: {task.status}"
        task.write_json(claimed_path)
        logger.error("任务非 Normal 状态：%s status=%s", task.task_id, task.status)
        return 1

    # 检查本地是否已存在完整的转写结果
    result_dir = ctx.config.temp_dir / "server_results" / task.task_id
    if result_dir.exists() and (result_dir / "task.json").exists():
        logger.info("本地已存在转写结果：%s，跳过转写过程", result_dir)
        return 0

    try:
        audio = AudioService(ctx.config, logger)
        audio_files = audio.get_audio_files_for_server(task)
        transcriber = Transcriber(ctx.config.path("server.faster_whisper_path"), ctx.config.temp_dir, logger)
        result_dir = transcriber.transcribe_audio_files(task, audio_files)
        logger.info("转写结果已就绪：%s", result_dir)
        return 0
    except Exception as exc:
        task.last_error = str(exc)
        task.write_json(claimed_path)
        logger.exception("任务 %s 转写失败：%s", task.task_id, exc)
        return 1


def publish(ctx: CommandContext, args, logger: logging.Logger, *, sync: bool = True) -> int:
    queue = ctx.queue(logger, sync=sync)
    server_id = ctx.server_id(args)

    claimed = queue.find_claimed_task(server_id)
    if not claimed:
        logger.info("节点 %s 没有已认领的任务", server_id)
        return 1

    claimed_path, task = claimed
    result_dir = ctx.config.temp_dir / "server_results" / task.task_id

    if result_dir.exists() and (result_dir / "task.json").exists():
        retry_interval = 10
        attempt = 0
        while True:
            attempt += 1
            try:
                queue.publish_result(claimed_path, task, result_dir)
                queue.commit_and_push(f"{server_id} publish {task.task_id}")
                break
            except Exception as exc:
                logger.warning(
                    "发布推送失败 (第 %d 次)：%s。%s 秒后重试...",
                    attempt, exc, retry_interval,
                )
                import time as _time

                _time.sleep(retry_interval)
                try:
                    queue = ctx.queue(logger, sync=True)
                except Exception as sync_exc:
                    logger.warning("重试前同步队列失败：%s", sync_exc)
                claimed = queue.find_claimed_task(server_id)
                if claimed:
                    claimed_path, task = claimed

        logger.info("已发布任务结果：%s", task.task_id)
        if args.keep_local_result:
            logger.info("保留本地结果目录：%s", result_dir)
        else:
            import shutil

            shutil.rmtree(result_dir)
            logger.info("已删除本地结果目录：%s", result_dir)
        return 0

    if not task.last_error:
        logger.error("任务 %s 既无本地结果也无失败标记", task.task_id)
        return 1

    if task.attempts < task.max_attempts and _is_retryable_error(task.last_error):
        queue.return_to_pending(claimed_path, task, task.last_error)
        queue.commit_and_push(f"{server_id} return {task.task_id}")
        logger.warning("任务已退回 pending 队列：%s 原因=%s", task.task_id, task.last_error)
        return 1

    queue.move_to_failed(claimed_path, task, task.last_error, server_id)
    queue.commit_and_push(f"{server_id} fail {task.task_id}")
    logger.error("任务已移至 failed 队列：%s 原因=%s", task.task_id, task.last_error)
    return 1


def once(ctx: CommandContext, args, logger: logging.Logger, *, sync: bool = True) -> int:
    claimed_code = claim(ctx, args, logger, sync=sync)
    if claimed_code != 0:
        return claimed_code

    transcribe_code = transcribe(ctx, args, logger)
    publish_code = publish(ctx, args, logger, sync=False)
    if transcribe_code == 0 and publish_code == 0:
        return 0
    return 1


def run(ctx: CommandContext, args, logger: logging.Logger) -> int:
    try:
        logger.info("正在初始化并同步 queue 仓库...")
        ctx.queue(logger, sync=True)
    except Exception as exc:
        logger.warning("初始化同步 queue 仓库失败：%s", exc)

    try:
        release_claimed(ctx, args, logger, sync=False)
    except Exception as exc:
        logger.warning("初始释放过期任务失败：%s", exc)

    # 启动时尝试发布上次未成功推送的结果
    try:
        publish_code = publish(ctx, args, logger, sync=False)
        if publish_code == 0:
            logger.info("启动时成功发布了上次未推送的结果")
    except Exception as exc:
        logger.warning("启动时尝试发布上次结果失败：%s", exc)

    max_tasks = int(args.max_tasks or ctx.config.get("server.max_tasks", 0))
    interval = int(args.interval or ctx.config.get("server.interval", 5))
    processed = 0
    had_failure = False
    should_sync = False

    while True:
        if max_tasks and processed >= max_tasks:
            logger.info("已达到最大任务数上限 %s，停止运行服务端", max_tasks)
            break

        if should_sync:
            try:
                logger.info("正在循环开始时同步 queue 仓库...")
                ctx.queue(logger, sync=True)
                should_sync = False
            except Exception as exc:
                logger.warning("循环开始时同步 queue 仓库失败：%s。%s 秒后重试...", exc, interval)
                had_failure = True
                time.sleep(interval)
                continue

        try:
            code = once(ctx, args, logger, sync=False)
            if code == 0:
                processed += 1
                logger.info("已完成服务端任务数：%s", processed)
                should_sync = True
                continue
            if code == 1:
                queue = ctx.queue(logger, sync=False)
                server_id = ctx.server_id(args)
                if not queue.find_claimed_task(server_id):
                    logger.info("队列中无待处理任务，正在退出...")
                    break
                had_failure = True
                logger.warning("任务失败但状态已处理，%s 秒后继续运行", interval)
                time.sleep(interval)
                should_sync = True
                continue
            had_failure = True
            break
        except Exception as exc:
            had_failure = True
            logger.error("服务端运行周期发生异常：%s。%s 秒后重试...", exc, interval)
            time.sleep(interval)
            should_sync = True
            continue

    logger.info("服务端运行总结：已处理任务数=%s 是否发生失败=%s", processed, had_failure)
    return 1 if had_failure else 0


def _is_retryable_error(error: str) -> bool:
    lowered = error.lower()
    non_retryable = ("invalid task", "status is not normal", "unavailable")
    return not any(marker in lowered for marker in non_retryable)
