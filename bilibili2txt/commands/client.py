from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

from ..config import CommandContext
from ..models import Task
from ..services.ai import AIService, format_api_error
from ..services.audio import AudioService
from ..services.bilibili import BilibiliService
from ..services.gitqueue import GitQueue
from ..services.markdown import build_markdown, md_path_for, parse_transcript_filename
from ..services.webdav import WebDavClient


def scan(ctx: CommandContext, args, logger: logging.Logger) -> int:
    db = ctx.database()
    service = BilibiliService(ctx.config, logger)

    if not service.login():
        logger.error("Bilibili 登录失败")
        return 1

    output_dir = ctx.config.temp_dir / "tasks"
    output_dir.mkdir(parents=True, exist_ok=True)
    max_pages = int(args.max_pages or 1)
    groups = args.group if args.group else None
    scrape_duration_max = int(ctx.config.get("bilibili.scrape_duration_max", 7200))

    created = 0
    skipped = 0
    for info in service.iter_target_videos(args.up_mid, groups=groups, max_pages=max_pages):
        bvid = str(info["bvid"])
        if db.video_exists(bvid):
            logger.debug("跳过已存在的视频: %s", bvid)
            skipped += 1
            continue

        info.update(service.get_video_detail(bvid=bvid))
        task = Task.from_bilibili_info(info)
        if task.duration > scrape_duration_max:
            task.status = "too_long"

        # Delete previous task files for the same bvid if they exist
        for old_file in output_dir.glob(f"*_{bvid}.json"):
            try:
                old_file.unlink()
                logger.info("已删除 %s 的旧任务文件: %s", bvid, old_file)
            except Exception as e:
                logger.warning("删除旧任务文件 %s 失败: %s", old_file, e)

        path = output_dir / task.filename
        task.write_json(path)
        db.upsert_video(task)
        db.upsert_task(task, path, "local")
        logger.info("已创建任务: %s status=%s duration=%s path=%s", task.task_id, task.status, task.duration, path)
        created += 1

    logger.info("扫描总结: 已创建=%s 已跳过=%s", created, skipped)
    return 0


def submit(ctx: CommandContext, args, logger: logging.Logger) -> int:
    queue = ctx.queue(logger)
    db = ctx.database()

    input_dir = Path(args.input) if args.input else ctx.config.temp_dir / "tasks"
    submitted_dir = ctx.config.data_dir / "tasks" / "submitted"
    submitted_dir.mkdir(parents=True, exist_ok=True)

    files = _collect_json_files(input_dir)
    if not files:
        logger.info("在 %s 中未找到任何任务文件", input_dir)
        return 0

    succeeded = 0
    skipped = 0
    failed = 0
    for path in files:
        try:
            task = Task.from_file(path)
        except Exception as exc:
            logger.error("无效的任务文件 %s: %s", path, exc)
            try:
                path.unlink()
                logger.info("已删除无效任务文件: %s", path)
            except Exception as e:
                logger.warning("删除无效任务文件 %s 失败: %s", path, e)
            failed += 1
            continue

        if task.status != "normal":
            logger.info("跳过非 normal 状态的任务 %s status=%s", task.task_id, task.status)
            try:
                path.unlink()
                logger.info("已删除非 normal 任务文件: %s", path)
            except Exception as e:
                logger.warning("删除非 normal 任务文件 %s 失败: %s", path, e)
            skipped += 1
            continue

        if queue.task_exists(task.task_id):
            logger.info("跳过重复任务 %s", task.task_id)
            try:
                path.unlink()
                logger.info("已删除重复任务文件: %s", path)
            except Exception as e:
                logger.warning("删除重复任务文件 %s 失败: %s", path, e)
            skipped += 1
            continue

        queue.add_pending_task(task)
        db.upsert_task(task, path, "submitted")
        db.mark_task_submitted(task.task_id)
        shutil.move(str(path), str(submitted_dir / path.name))
        logger.info("已从 %s 提交任务 %s", path, task.task_id)
        succeeded += 1

    queue.commit_and_push(f"submit {succeeded} task(s)")
    logger.info("提交总结: 成功=%s 跳过=%s 失败=%s", succeeded, skipped, failed)
    return 0 if failed == 0 else 1


def prepare_audio(ctx: CommandContext, args, logger: logging.Logger) -> int:
    min_duration = int(args.min_duration or ctx.config.get("client.local_download_audio_seconds", 1800))
    queue = GitQueue(ctx.config.queue_dir, logger)
    audio = AudioService(ctx.config, logger)

    queue.ensure_layout()
    queue.sync()

    webdav = WebDavClient.from_config(ctx.config, logger)
    remote_files = webdav.list_files()

    temp_tasks_dir = ctx.config.temp_dir / "tasks"
    pending_dir = queue.pending_dir
    failed_dir = queue.failed_dir

    files = []
    if temp_tasks_dir.exists():
        files.extend(_collect_json_files(temp_tasks_dir, recursive=True))
    if pending_dir.exists():
        files.extend(_collect_json_files(pending_dir, recursive=True))
    if failed_dir.exists():
        files.extend(_collect_json_files(failed_dir, recursive=True))

    # Deduplicate files by absolute path to avoid duplicate processing
    seen_paths = set()
    unique_files = []
    for f in files:
        resolved = f.resolve()
        if resolved not in seen_paths:
            seen_paths.add(resolved)
            unique_files.append(f)
    files = unique_files

    if not files:
        logger.info("未找到用于 prepare-audio 的任何任务文件")
        return 0

    succeeded = 0
    skipped = 0
    failed = 0
    queue_modified = False

    for path in files:
        try:
            task = Task.from_file(path)
        except Exception as exc:
            logger.error("无效任务文件 %s: %s", path, exc)
            failed += 1
            continue

        is_failed_task = _is_under(path, failed_dir)

        if is_failed_task:
            if task.client_retries >= 3:
                logger.info("跳过已达到最大客户端重试次数的任务: %s client_retries=%s", task.task_id, task.client_retries)
                skipped += 1
                continue
            if not task.last_error or "yt-dlp" not in task.last_error:
                logger.info("跳过非 yt-dlp 失败任务: %s last_error=%s", task.task_id, task.last_error)
                skipped += 1
                continue
        else:
            if task.status != "normal":
                logger.info("跳过非 normal 状态任务: %s status=%s", task.task_id, task.status)
                skipped += 1
                continue

        if task.duration <= min_duration:
            logger.info("跳过过短任务: %s 时长=%s <= %s", task.task_id, task.duration, min_duration)
            skipped += 1
            continue

        audio_on_webdav = False
        if f"{task.bvid}.mp3" in remote_files:
            audio_on_webdav = True
        else:
            for rf in remote_files:
                if rf.startswith(f"{task.bvid}_") and rf.endswith(".mp3"):
                    audio_on_webdav = True
                    break

        if audio_on_webdav:
            if is_failed_task:
                logger.info("音频已在 WebDAV 上存在，将失败任务移回 pending: %s", task.task_id)
                task.reset_for_resubmit()
                queue.add_pending_task(task)
                if path.exists():
                    path.unlink()
                failed_task_dir = failed_dir / task.task_id
                if failed_task_dir.exists() and failed_task_dir.is_dir():
                    try:
                        shutil.rmtree(failed_task_dir)
                    except Exception as e:
                        logger.warning("删除失败任务目录 %s 失败: %s", failed_task_dir, e)
                queue_modified = True
                succeeded += 1
            else:
                logger.info("跳过已在 WebDAV 上存在的任务: %s (%s.mp3)", task.task_id, task.bvid)
                skipped += 1
            continue

        try:
            if is_failed_task:
                task.client_retries += 1
                task.write_json(path)
                queue_modified = True

            audio_files = audio.download_task_audio(task)
            if not audio.upload_task_audio(task, audio_files):
                failed += 1
                continue

            if is_failed_task:
                task.reset_for_resubmit()
                queue.add_pending_task(task)
                if path.exists():
                    path.unlink()
                failed_task_dir = failed_dir / task.task_id
                if failed_task_dir.exists() and failed_task_dir.is_dir():
                    try:
                        shutil.rmtree(failed_task_dir)
                    except Exception as e:
                        logger.warning("删除失败任务目录 %s 失败: %s", failed_task_dir, e)
                queue_modified = True

            succeeded += 1
        except Exception as exc:
            logger.exception("为 %s 准备音频失败: %s", task.task_id, exc)
            failed += 1

    if queue_modified:
        try:
            queue.commit_and_push("prepare-audio: retry failed tasks")
        except Exception as exc:
            logger.error("提交队列修改失败: %s", exc)

    logger.info("准备音频总结: 成功=%s 跳过=%s 失败=%s", succeeded, skipped, failed)
    return 0 if failed == 0 else 1


def resubmit_missing(ctx: CommandContext, args, logger: logging.Logger) -> int:
    queue = ctx.queue(logger)
    db = ctx.database()

    excludes = set()
    if getattr(args, "exclude", None):
        for item in args.exclude:
            for subitem in item.split(","):
                val = subitem.strip()
                if val:
                    excludes.add(val)

    if getattr(args, "failed", False):
        input_dir = queue.failed_dir
        files = _collect_json_files(input_dir, recursive=True)
    else:
        input_dir = Path(args.input) if args.input else ctx.config.temp_dir / "missing_tasks"
        files = _collect_json_files(input_dir)

    if not files:
        logger.info("在 %s 中未找到任何丢失任务文件", input_dir)
        return 1

    succeeded = 0
    skipped = 0
    queue_modified = False
    for path in files:
        try:
            task = Task.from_file(path)
        except Exception as exc:
            logger.error("无效的丢失任务文件 %s: %s", path, exc)
            continue

        if task.task_id in excludes or task.bvid in excludes:
            logger.info("排除任务 %s", task.task_id)
            continue

        is_failed_task = _is_under(path, queue.failed_dir)
        existing = queue.task_is_pending_or_claimed(task.task_id)
        if existing:
            logger.info("跳过丢失任务 %s (已在排队或处理中: %s, 文件: %s)", task.task_id, existing, path)
            if is_failed_task:
                failed_task_dir = queue.failed_dir / task.task_id
                if failed_task_dir.exists() and failed_task_dir.is_dir():
                    try:
                        shutil.rmtree(failed_task_dir)
                        logger.info("已删除已在排队或处理中的失败任务残留目录: %s", failed_task_dir)
                        queue_modified = True
                    except Exception as e:
                        logger.warning("删除失败任务残留目录 %s 失败: %s", failed_task_dir, e)
            skipped += 1
            continue

        task.reset_for_resubmit()
        queue.add_pending_task(task)
        db.upsert_task(task, path, "pending")
        logger.info("已重新提交丢失任务 %s", task.task_id)
        if is_failed_task:
            failed_task_dir = queue.failed_dir / task.task_id
            if failed_task_dir.exists() and failed_task_dir.is_dir():
                try:
                    shutil.rmtree(failed_task_dir)
                    logger.info("已删除重新提交的失败任务目录: %s", failed_task_dir)
                except Exception as e:
                    logger.warning("删除失败任务目录 %s 失败: %s", failed_task_dir, e)
        succeeded += 1
        queue_modified = True

    if queue_modified:
        queue.commit_and_push(f"resubmit/cleanup missing {succeeded} task(s)")
    logger.info("重新提交丢失任务总结: 成功=%s 跳过=%s", succeeded, skipped)
    return 0


def collect(ctx: CommandContext, args, logger: logging.Logger) -> int:
    queue = ctx.queue(logger)
    db = ctx.database()

    save_dir = ctx.config.data_dir / "save"
    save_dir.mkdir(parents=True, exist_ok=True)
    missing_dir = ctx.config.temp_dir / "missing_tasks"

    submitted_dir = ctx.config.data_dir / "tasks" / "submitted"

    succeeded = 0
    skipped = 0
    failed = 0
    for result_dir in queue.iter_results():
        task_file = result_dir / "task.json"
        if not task_file.exists():
            logger.error("跳过不含 task.json 的结果: %s", result_dir)
            failed += 1
            continue
        task = Task.from_file(task_file)
        transcript_files = sorted(
            path for path in result_dir.iterdir() if path.suffix in {".text", ".txt", ".srt"}
        )
        if not transcript_files:
            logger.error("跳过不含文稿文件的结果: %s", result_dir)
            failed += 1
            continue

        all_exist = True
        copied_any = False
        for transcript in transcript_files:
            target = save_dir / _final_transcript_name(task, transcript)
            if target.exists() and not args.force:
                logger.info("跳过已存在的文稿: %s", target)
                skipped += 1
                continue
            all_exist = False
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(transcript, target)
            logger.info("已收集文稿: %s -> %s", transcript, target)
            copied_any = True

        if copied_any or all_exist or args.force:
            done_path = queue.collect_result_to_done(result_dir)
            if done_path.exists():
                shutil.rmtree(done_path)
                logger.info("已删除 queue/done 中的已收集结果: %s", done_path)
            db.mark_task_completed(task.task_id)
            _delete_matching_missing(missing_dir, task, logger)
            _delete_matching_submitted(submitted_dir, task, logger)
            succeeded += 1

    # Clean up any leftover done directories if the corresponding BVID already exists in data/save
    if queue.done_dir.exists():
        for done_task_dir in sorted(queue.done_dir.iterdir()):
            if not done_task_dir.is_dir():
                continue
            task_id = done_task_dir.name
            bvid = task_id
            task_json_file = done_task_dir / "task.json"
            if task_json_file.exists():
                try:
                    bvid = Task.from_file(task_json_file).bvid
                except Exception:
                    pass
            already_collected = any(bvid in path.name for path in save_dir.glob(f"*{bvid}*"))
            if already_collected:
                logger.info("检测到已收集的文稿，自动清理已完成的残留目录: %s (BVID: %s)", done_task_dir, bvid)
                try:
                    shutil.rmtree(done_task_dir)
                    succeeded += 1
                except Exception as e:
                    logger.warning("删除已完成残留目录 %s 失败: %s", done_task_dir, e)

    if succeeded:
        queue.commit_and_push(f"collect {succeeded} result(s)")
    logger.info("收集总结: 成功=%s 跳过=%s 失败=%s", succeeded, skipped, failed)
    return 0 if failed == 0 else 1


def render(ctx: CommandContext, args, logger: logging.Logger) -> int:
    db = ctx.database()
    ai = AIService(ctx.config, logger)
    ai.test_and_filter_providers()
    save_dir = ctx.config.data_dir / "save"
    markdown_root = ctx.config.data_dir / "markdown"

    text_files = sorted(save_dir.glob("*.text"))
    if args.bvid:
        text_files = [path for path in text_files if args.bvid in path.name]
    if not text_files:
        logger.info("在 %s 中未找到任何可渲染的 .text 文件", save_dir)
        return 1

    succeeded = 0
    skipped = 0
    failed = 0

    to_render = []
    for text_file in text_files:
        meta = parse_transcript_filename(text_file)
        if not meta:
            logger.info("跳过无法识别的文稿文件名: %s", text_file.name)
            skipped += 1
            continue
        target = md_path_for(meta, markdown_root, text_file)
        if target.exists() and not args.force:
            logger.debug("跳过已存在的 Markdown: %s", target)
            skipped += 1
            continue
        to_render.append((text_file, meta, target))

    total = len(to_render)
    for idx, (text_file, meta, target) in enumerate(to_render, 1):
        transcript = text_file.read_text(encoding="utf-8")
        try:
            ai_provider, summary = ai.summarize(transcript)
            content = build_markdown(meta, transcript, summary, ai_provider)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            db.record_render(meta.bvid, text_file, target, ai_provider, "success")
            logger.info("已生成 Markdown [%d/%d]: %s (由 %s 生成)", idx, total, target, ai_provider)
            succeeded += 1
        except Exception as exc:
            formatted_err = format_api_error(exc)
            db.record_render(meta.bvid, text_file, None, None, "failed", formatted_err)
            logger.error("为 %s 生成总结失败 [%d/%d]: %s", text_file, idx, total, formatted_err)
            failed += 1
            continue

    logger.info("渲染总结: 成功=%s 跳过=%s 失败=%s", succeeded, skipped, failed)
    return 0 if failed == 0 else 1


def sync(ctx: CommandContext, args, logger: logging.Logger) -> int:
    service = ctx.netdisk_sync(logger)
    stats = service.sync(force=args.force)
    logger.info(
        "同步总结: 已拷贝=%s 已跳过=%s 冲突数=%s 已归档数=%s",
        stats.copied,
        stats.skipped,
        stats.conflicts,
        stats.archived,
    )
    return 0


def finish(ctx: CommandContext, args, logger: logging.Logger) -> int:
    from ..services.gitrepo import GitRepo
    repo = GitRepo(ctx.config.data_dir, logger)
    message = getattr(args, "message", None) or "update"
    repo.commit_and_push_all(message)
    return 0


def env_check(ctx: CommandContext, logger: logging.Logger) -> bool:
    logger.info("=== 开始环境检查 ===")

    # 1. 测试 Bilibili 下载并上传到 WebDAV
    logger.info("--- 测试 Bilibili 真实下载并上传到 WebDAV ---")
    try:
        test_url = "https://www.bilibili.com/video/BV1v49YBHESJ"
        logger.info("Bilibili 下载测试地址: %s", test_url)

        test_task = Task(
            task_id="env_check_test",
            bvid="BV1v49YBHESJ",
            title="env_check_test",
            up_name="test",
            up_mid=None,
            pubdate=None,
            duration=0,
            cid=None,
            status="normal",
            source_url=test_url,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        audio = AudioService(ctx.config, logger)
        audio_files = audio.download_task_audio(test_task)
        logger.info("Bilibili 下载测试通过（已下载）。现在开始测试上传...")

        webdav = WebDavClient.from_config(ctx.config, logger)
        for local_path in audio_files:
            if not local_path.exists():
                continue
            logger.info("准备上传到 WebDAV: %s", local_path.name)
            remote_name = f"test_download_{local_path.name}"
            if webdav.upload(local_path, remote_name):
                logger.info("WebDAV 上传测试成功: %s。正在清理...", remote_name)
                local_path.unlink(missing_ok=True)
                webdav.delete(remote_name)
            else:
                logger.error("WebDAV 上传测试失败: %s", local_path.name)
                return False

        if not audio_files:
            logger.warning("未找到下载的音频文件，下载可能失败。")
            return False

    except Exception as e:
        logger.error("Bilibili 下载与 WebDAV 上传测试遇到异常: %s", e)
        return False

    # 2. 测试 WebDAV 获取列表
    logger.info("--- 测试 WebDAV 获取列表 ---")
    try:
        webdav = WebDavClient.from_config(ctx.config, logger)
        webdav_files = webdav.list_files()
        logger.info("WebDAV 列表获取测试通过，共 %d 个文件。", len(webdav_files))
    except Exception as e:
        logger.error("WebDAV 列表测试遇到异常: %s", e)
        return False

    # 3. 测试 Git Pull
    logger.info("--- 测试 Git Pull ---")
    try:
        queue = GitQueue(ctx.config.queue_dir, logger)
        queue.ensure_layout()
        logger.info("正在对 %s 执行 git pull (sync)...", ctx.config.queue_dir)
        queue.sync()
        logger.info("Git Pull 测试通过。")
    except Exception as e:
        logger.error("Git Pull 测试遇到异常: %s", e)
        return False

    logger.info("=== 环境检查全部通过 ===\n")
    return True


def run(ctx: CommandContext, args, logger: logging.Logger) -> int:
    logger.info("客户端运行启动")

    if not getattr(args, "skip_env_check", False):
        if not env_check(ctx, logger):
            logger.error("环境检查未通过，终止运行。")
            return 1
        logger.info("环境检查通过，继续执行客户端流程。")
    else:
        logger.info("已设置 --skip-env-check，跳过环境检查")
    if getattr(args, "skip_scan", False):
        logger.info("已设置 --skip-scan，跳过扫描步骤")
        scan_code = 0
    else:
        logger.info("====== scan ======")
        scan_code = scan(ctx, args, logger)
        if scan_code != 0:
            logger.info("扫描未产生可运行的任务，或扫描失败。代码=%s", scan_code)
            return scan_code

    logger.info("====== prepare-audio ======")
    prepare_code = prepare_audio(ctx, args, logger)
    if prepare_code != 0:
        logger.warning("prepare-audio 返回代码=%s；继续提交因为服务端自身也可以下载", prepare_code)

    logger.info("====== submit ======")
    submit_code = submit(ctx, args, logger)
    if submit_code != 0:
        return submit_code

    if not args.wait:
        return 0

    logger.info("=== 开始执行 chrome_bookmark_manager ===")
    try:
        import sys
        _bookmark_dir = Path(__file__).resolve().parent.parent.parent.parent / "python_utils_private"
        if str(_bookmark_dir) not in sys.path:
            sys.path.insert(0, str(_bookmark_dir))
        from chrome_bookmark_manager import manage_chrome
        manage_chrome('open', logger)
    except Exception as e:
        logger.warning("启动 chrome_bookmark_manager 失败: %s", e)
    logger.info("=== chrome_bookmark_manager 执行完成 ===")

    logger.info("====== wait-for-queue-completion ======")
    _wait_for_queue_completion(ctx, args, logger)

    logger.info("=== 关闭已打开的 Chrome 窗口 ===")
    try:
        import sys
        _bookmark_dir = Path(__file__).resolve().parent.parent.parent.parent / "python_utils_private"
        if str(_bookmark_dir) not in sys.path:
            sys.path.insert(0, str(_bookmark_dir))
        from chrome_bookmark_manager import manage_chrome
        manage_chrome('close', logger)
    except Exception as e:
        logger.warning("关闭 chrome_bookmark_manager 失败: %s", e)

    logger.info("====== collect ======")
    collect_code = collect(ctx, args, logger)
    if collect_code != 0:
        return collect_code

    logger.info("====== render ======")
    render_code = render(ctx, args, logger)

    logger.info("====== sync ======")
    sync_code = sync(ctx, args, logger)

    if render_code == 0 and sync_code == 0:
        logger.info("====== finish ======")
        return finish(ctx, args, logger)
    return 1


def _wait_for_queue_completion(ctx: CommandContext, args, logger: logging.Logger) -> None:
    queue = GitQueue(ctx.config.queue_dir, logger)
    interval = int(ctx.config.get("client.wait_interval_seconds", 60))
    timeout = int(ctx.config.get("client.wait_timeout_seconds", 0))
    start = time.time()
    while True:
        queue.sync(max_retries=None)
        pending_count = len(list(queue.pending_dir.glob("*.json"))) if queue.pending_dir.exists() else 0
        claimed_count = len(list(queue.claimed_dir.rglob("*.json"))) if queue.claimed_dir.exists() else 0
        logger.info("等待队列中: pending=%s claimed=%s", pending_count, claimed_count)
        if pending_count == 0 and claimed_count == 0:
            return
        if timeout and time.time() - start > timeout:
            logger.warning("等待超时已达到: %ss", timeout)
            return
        time.sleep(interval)


def _final_transcript_name(task: Task, transcript: Path) -> str:
    dt = datetime.fromtimestamp(task.pubdate or 0, tz=timezone(timedelta(hours=8)))
    timestamp = dt.strftime("%Y-%m-%d_%H-%M-%S")
    title = _sanitize_filename(task.title)[:50]
    part = ""
    stem = transcript.stem
    if stem.startswith("transcript_"):
        part = "_" + stem.removeprefix("transcript_")
    return f"[{timestamp}][{task.up_name}][{title}][{task.bvid}{part}]{transcript.suffix}"


def _sanitize_filename(value: str) -> str:
    invalid = '<>:"/\\|?*'
    return value.translate(str.maketrans(invalid, "_" * len(invalid))).strip()


def _delete_matching_missing(missing_dir: Path, task: Task, logger: logging.Logger) -> None:
    if not missing_dir.exists():
        return
    for path in missing_dir.glob("*.json"):
        try:
            missing = Task.from_file(path)
            match = missing.task_id == task.task_id or missing.bvid == task.bvid
        except Exception:
            match = task.task_id in path.name or task.bvid in path.name
        if match:
            path.unlink()
            logger.info("已删除已解决的丢失任务: %s", path)


def _delete_matching_submitted(submitted_dir: Path, task: Task, logger: logging.Logger) -> None:
    if not submitted_dir.exists():
        return
    for path in submitted_dir.glob("*.json"):
        try:
            submitted = Task.from_file(path)
            match = submitted.task_id == task.task_id or submitted.bvid == task.bvid
        except Exception:
            match = task.task_id in path.name or task.bvid in path.name
        if match:
            path.unlink()
            logger.info("已删除已收集的提交任务文件: %s", path)


def _collect_json_files(input_path: Path, recursive: bool = False) -> list[Path]:
    if input_path.is_file() and input_path.suffix.lower() == ".json":
        return [input_path]
    if input_path.is_dir():
        return sorted(input_path.rglob("*.json") if recursive else input_path.glob("*.json"))
    return []


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _is_download_failure(error: str | None) -> bool:
    if not error:
        return False
    lowered = error.lower()
    return any(token in lowered for token in ("download", "audio", "yt-dlp", "webdav", "http error"))
