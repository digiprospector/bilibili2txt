from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import CommandContext
from ..database import migrate_main_database
from ..models import Task
from ..services.audio import AudioService
from ..services.bilibili import BilibiliService
from ..services.ai import AIService, format_api_error
from ..services.gitrepo import GitRepo
from ..services.webdav import WebDavClient
from ..services.video_id import parse_video_input
from ..services.markdown import render_or_update_summary


def check_missing(ctx: CommandContext, _args, logger: logging.Logger) -> int:
    submitted_dir = ctx.config.data_dir / "tasks" / "submitted"
    save_dir = ctx.config.data_dir / "save"
    output_dir = ctx.config.temp_dir / "missing_tasks"
    output_dir.mkdir(parents=True, exist_ok=True)

    text_names = [path.name for path in save_dir.glob("*.text")] if save_dir.exists() else []
    missing = 0
    checked = 0
    for task_file in sorted(submitted_dir.glob("*.json")):
        task = Task.from_file(task_file)
        if task.status != "normal":
            logger.info("跳过非 normal 状态的已提交任务: %s status=%s", task.task_id, task.status)
            continue
        checked += 1
        if any(task.bvid in name for name in text_names):
            continue
        target = output_dir / task_file.name
        shutil.copy2(task_file, target)
        logger.info("已导出丢失的任务: %s -> %s", task_file, target)
        missing += 1

    logger.info("检查丢失任务总结: 已检查=%s 丢失=%s", checked, missing)
    return 0


def webdav_upload(ctx: CommandContext, args, logger: logging.Logger) -> int:
    file_path = Path(args.file).resolve()
    if not file_path.is_file():
        logger.error("不是文件: %s", file_path)
        return 1
    client = WebDavClient.from_config(ctx.config, logger)
    if not client.upload(file_path, show_progress=True):
        return 1
    if not args.keep:
        file_path.unlink()
        logger.info("上传后删除了本地文件: %s", file_path)
    return 0


def webdav_clean(ctx: CommandContext, args, logger: logging.Logger) -> int:
    client = WebDavClient.from_config(ctx.config, logger)
    try:
        files = _list_webdav_files(client, logger)
    except Exception as exc:
        logger.error("WebDAV 清理失败: %s", exc)
        return 1
    logger.info("待删除的 WebDAV 文件数: %s", len(files))
    failed = 0
    for name in files:
        logger.info("WebDAV 清理目标: %s", name)
        if args.dry_run:
            continue
        if not client.delete(name):
            failed += 1
    logger.info("WebDAV 清理总结: 总数=%s 失败=%s dry_run=%s", len(files), failed, args.dry_run)
    return 0 if failed == 0 else 1


def push_data(ctx: CommandContext, args, logger: logging.Logger) -> int:
    repo = GitRepo(ctx.config.data_dir, logger)
    message = args.message or "update"
    repo.commit_and_push_all(message)
    return 0


def migrate_main_db(_ctx: CommandContext, args, logger: logging.Logger) -> int:
    stats = migrate_main_database(Path(args.source_db), Path(args.target_db), dry_run=args.dry_run)
    logger.info(
        "迁移主数据库总结: 已读取=%s 已插入=%s 已更新=%s dry_run=%s",
        stats["read"],
        stats["inserted"],
        stats["updated"],
        args.dry_run,
    )
    return 0


def _list_webdav_files(client: WebDavClient, logger: logging.Logger) -> list[str]:
    import xml.etree.ElementTree as ET
    import requests

    try:
        response = requests.request(
            "PROPFIND",
            client.base_url + "/",
            auth=(client.username, client.password),
            headers={"Depth": "1"},
            timeout=30,
            proxies=client.proxies,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        resp_text = ""
        if hasattr(exc, "response") and exc.response is not None:
            resp_text = f"。服务器返回内容:\n{exc.response.text[:1000]}"
        raise RuntimeError(f"请求 WebDAV 失败: {exc}{resp_text}") from exc

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise ValueError(f"解析 WebDAV XML 响应失败: {exc}。服务器返回内容的前 1000 个字符为:\n{response.text[:1000]}") from exc

    ns = {"d": "DAV:"}
    files: list[str] = []
    for href in root.findall(".//d:href", ns):
        text = href.text or ""
        if text.endswith("/"):
            continue
        files.append(Path(text).name)
    logger.info("已列出 WebDAV 文件数: %s", len(files))
    return files


STOCK_TEST_CONTENT = """大家好,今天是2026年4月5号,星期天。
每周安慰一下吧,特别需要安慰,对吧?
你看一下这一周的周K线吧,你有什么好忘的呢?
他这一周的周K线特意在收盘上说了少四个点吧。
说一个阴线,上阴线,感觉好像不行了,对吧?
这不是惯用的套路吗?
周末,又在接下来的前一天,说一个阴线。
再前一个星期,他收了一根大长腿,不好看,让人感觉好像要上去了,对吧?
所以说上一个星期,大家的希望很多。
那这个星期他收一个阴线,那不就好了吗?
再镇一镇,差不多了,对不对?
没什么好慌的。
你看那个周末的长线的利多消息,长线资金入市啊,对吧?
短线要查那个交易的新规啊,包括那个降准降息,稳健的偏宽松的资金政策。
这些都是那个,我们的大哥货没有出完,所以这些东西都要在,知道吧?
最想说的是什么呢?
最想说的是,现在很像21年的三月份。
这个21年其实过去没多少年。
你去看指数上面,21年2月份,其实50啊什么的都到头了,下来了。
你在上阵指数上看不清楚,你看上阵50的指数的话就看得出来。
看上阵指数你只能看到21年的2月一波上来,下来。
然后呢,其实从21年的三月开始,再上,这是一个分隔的大切换。
你去看很多的板块的指数就知道。
分隔的大切换就发生在21年的两月到三月之前。
也就是说,我们现在很容易,或者说大概率会发生一个分隔切换,可能就在四月五月。
那么什么没涨过呢?
我也不用说了吧?
什么没涨过呢?
券券啊,食品饮料啊,包括底部的医药啊,还有一些什么科技的别类,对吧?
没有涨过的,都会切换。
涨过的时候呢?
商业航天啊,有色啊,CPU啊,对不对?
现在你如果被套在那个,这些里面的话,你是不是瑟瑟发抖啊?
特别是已经组成过的,你没有经历过的,你就经历一次你才知道。
同样现在99.9%的股民被套,但是被套在不同的图形里面,这个感觉效果是完全不一样的,对不对?
好吧,这个只有慢慢的时间来告诉你,你才能明白。
但95%以上的人,还没明白过来,就已经被淘汰了,好吧?
那你想想看,只要券券啊,50,包括300,这些都没有大涨过,那么大哥都还在里面,大哥还在里面,只不过是等待分割切换。
我说过了,最差也就是走21年的盘顶,盘一个三重顶,四重顶的这样一个结构。
这是最差的,更不要说连续拉升了,对吧?
所以说现在只不过是一次,两次,两次的一个大跌,就好比现在最差就像21年的2月,跌下来,然后分割切换,这是最差的。
还有什么好担心的呢?
对不对?
你要去所谓的改变持仓的规模也好,你的模式要改变也好,或者说你投入的资金要改变也好,也都应该把这一段时间熬过去。
你现在应该去想的,熬过去以后,我要怎么办?
或者说哪一部分资金拿出来?
或者说把盈利的拿出来?
你现在都认可的,拿出来不炒了什么的,真的,到了四五月份,五六月份,七八月份,让你回本了,赚了,你又不是这么想的,对吧?
这就是人啊,或者说这就是普通人。
好吧,还是说一些那个经验分享吧,这个东西对你有用,我觉得。
现在不看盘啊,我现在不看盘,我觉得非常舒服。
或者说我现在不看盘快熬不住的话,我相信看盘的人都已经崩溃了。
你会不看盘的人会比看盘的人高一个档次,就好比同样大家在跑步和骑自行车,不看盘的人就好像骑自行车,看盘的人就好像跑步。
你跑步能够和自行车的人跑到同样的公里数,就是说同样的熬过来了,对吧?
同样的从被套熬到盈利了。
你如果是天天看盘的话,那我觉得你是非常浪费的,你的潜力是非常可以做一个长线选手的,你如果不看盘的话,是不是?
也就是说你明明可以骑自行车,你非要选择跑步,那怎么关税呢?
你熬不住关税呢?
有自行车的,你可以不看盘的。
至于怎么做到不看盘,比如说刷剧也好,打游戏也好,找点其他事情做也好,这是你要想办法。
你人不能空下来,你被套住了空下来,那你肯定要看盘,你要找事情做。
好吧,这是实操的方法,你不要去想什么其他道理,实操是最重要的,因为实操可以让你做到账户里面有亏到盈利。
好,还有割肉,割肉这个事情只有一次和无数次,这个和什么家暴差不多,对吧?
割肉这个事情啊,你只要割过一次了,你就会无数次割下去。
这个东西就好像你怎么说呢?
你承认失败了,你承认你的这个所谓的模式是不对的。
那你要换一种模式,你想得都很好,换一种模式,但是不可能的,好吧,不可能的,你割肉只会割习惯了。
当然了,你割肉割下去一刀,然后重新买入一个票,对你来说应该是凤凰涅槃重生。
但是呢,大多数人不是,大多数人只是为了摆脱痛苦,摆脱痛苦以后制骰子,再来一局,对吧?
你是涅槃重生还是制骰子,重新来一局,你自己心里最清楚,好吧?
这个不要我说,你自己心里最清楚。
还有就是你同样买的票,关键还是那句话,你千万不要买在祖圣浪之后,就好像很多的现在上亚航天和有色都是祖圣浪过的,各国连续涨停过的。
连续涨停过,祖圣浪过,你进去以后……哎呀,怎么说呢?
你进去以后……哎,没法说,没法说,我不想说了,被淘汰也是正常的。
好吧,还有就是你如果现在买的票,没有祖圣浪过,是在箱体底部的,或者在成型的箱体中,哪怕现在跌到箱体底部,你去看,现在很多箱体,跌到箱体底部的票, 现在都是无量的。
跌下来,阴线可能3厘米,4厘米很吓人,但是是无量的。
你把这些阴线,无量的阴线,去看它箱体之前,我为什么说要看三年以上的箱体?
你现在跌下来这个箱体,你看这个量,在之前发生过没有?
我可以打保票说,99.9%都发生过,之前也发生过,也是3,4厘米,也是差不多光脚的。
为什么?
要吓唬你。
它又砸不出量,又要吓唬你,那只能用K线的形态来吓唬你。
用分时来看的话,就是一路下跌,收盘收到最低点,量放不出来,为什么量放不出来?
因为这个地方它放出量了,它如果放出量了,自买自卖的话,很有可能被懂的人,大资金的懂的人给抢掉货。
对吧?
它不可能去砸出量,它砸出量,自己的辛辛苦苦的底部筹码会被别人拿掉,然后人家底部拿了你的筹码,耗时间,主力怎么办?
很被动。
所以它不可能砸出量,不可能砸出量,但要砸出那个恶心的形态,就是光脚,然后呢,做分时一路下滑。
为什么分时一路下滑?
能做到分时一路下滑?
因为现在没有人,没有散户去接,所以它可以做到分时一路下滑。
好吧?
你会说,没有散户接,它为什么不敢砸出量呢?
没有散户接,不代表没有高手看,好吧?
那么同样的,就是让你看看前面,相提前面,这种尖尖头往下的,缩量的,现在出现的都是跟之前一模一样的。
再过个三四个月或者半年,你现在这个点,你又会看到这是一个很好的买点。
那么为什么现在又没有子弹了呢?
不就是因为你之前贪了,等不及了吗?
你现在也可以在这个地方滑一条线。
而且你可以看到现在下来的这个尖尖头的最好的买点,所谓的龙膝头,无人问清楚,缩量到极致的买点,和之前的这些尖尖头,是几乎在一条水平线上的,几乎这个区域。
你可以在这个区域滑一条线,或者说滑一个价格警示线,比如说这个价格警示线在五块,你滑掉,一般不要滑整数位,滑五块零五分,五块一,对吧?
滑掉这条线附近,那么这条线就出来乐。
等下次价格再到这里的时候提醒你,很多时候我在会员视频里面做的时候也是,我滑了这条线以后,当初连我自己都觉得这条线不可能到。
现在都到了,几乎都到了,现在到了以后就看你有没有子弹,一,有没有子弹,二,敢不敢买。
所以滑了这条线以后,你最好就设一个条件单,自动买入,买入多少仓位,买入多少量,你自己设好。
然后这个账户,你可以搞一个账户,一个人最多三个账户,你可以搞一个账户,存一笔钱,就做这个自动交易,对吧?
你滑好一条线,现在没到,等到了,自动买入。
买入以后,再滑一条线,到了这个价位,没有涨停,回落,回落卖出,回落超过百分之一了,自动卖出一半。
全部用一个账户,全自动操作,或者说这是半自动操作。
你看看,做下来一年两年,以后一定比你自己操作的要做得好。
好吧,这个说完了。
这个还没完。
这个现在如果是在箱体里面被套的话,我强烈建议你持有,持有了以后被套了,你一定要有一个被套,然后慢慢浮出水面,浮出水面以后你可以减半,但不要减完,我强烈建议你不要减完,不要减完,然后拿着。
实在受不了了,实在怕了,再减一半,哪怕留四分之一也留着,然后拿到他的连续涨停,所谓的主升。
你只要有过这样一次经验,你下一次选票你就心里有底了,这样的票我敢选,我只要控制好他这个票,单票的总仓位,我就敢拿,敢被套,敢被套的情况下不去看盘。
这是最重要的,然后拿到他,浮出水面,然后有一定盈利了,减半,降低仓位,使我更安心,然后剩下的仓位我敢拿到主升。
你一定要有这一整套的正向的反馈的经历以后,你才真正的,不能说合格,真正的有一个破壳而出的雏形了,就是从一只蛋变成一只鸡了。
你才是破壳而出,刚刚开始,你这个经历没有,你永远是一个蛋,这个蛋就是看有没有猎物把你吃掉,你是被动的,非常被动的,有没有各种各样的猎物不是要偷蛋吃吗?
你就是这个蛋,你没有任何反抗力,你一定要有这样一个正循环以后,你才刚刚破壳而出。
好了,今天就说到这里吧,不要担心了啊,关键还是你的模式是正确的,我做了那么多年,做下来以后,对于我们普通老百姓,99%的普通散户来说,只有这个模型是可以的,因为我现在周边存活下来的20年以上的老公民,基本上都是这个模型,只不过大家对于相体的理解,对于,呃,呃,怎么说呢?
选票的理解,到底是一路向下,多低算低算。
多低算安全,这个上面有分歧,但是对于整个大的概念,底部埋入,持有,熬,绝不割肉,然后呢,分辟出,这个是没有区别的。
好吧,拜拜了。"""


def check_ai(ctx: CommandContext, args, logger: logging.Logger) -> int:
    service = AIService(ctx.config, logger)
    
    if args.list:
        providers = service.providers()
        for provider in providers:
            logger.info(
                "AI 服务商: name=%s model=%s base_url=%s",
                provider.get("name"),
                provider.get("model"),
                provider.get("base_url"),
            )
        return 0

    if args.stock:
        logger.info("正在使用 A 股分析师 Prompt 进行测试总结...")
        try:
            name, result = service.summarize(STOCK_TEST_CONTENT, provider_name=args.name, model=args.model)
            logger.info("AI 总结完成 (服务商: %s):", name)
            print(result)
            return 0
        except Exception as exc:
            logger.error("AI 总结测试失败: %s", format_api_error(exc))
            return 1

    providers = service.providers()
    if args.name:
        providers = [provider for provider in providers if provider.get("name") == args.name]
    if not providers:
        logger.error("没有匹配的 AI 服务商")
        return 1

    success_count = 0
    for provider in providers:
        ok, message = service.test_provider(provider)
        if ok:
            success_count += 1
            logger.info("AI 测试成功: %s", message)
        else:
            logger.error("AI 测试失败: %s", message)
    return 0 if success_count else 1


def fix_summaries(_ctx: CommandContext, _args, _logger: logging.Logger) -> int:
    ctx = _ctx
    args = _args
    logger = _logger
    ai = AIService(ctx.config, logger)
    save_dir = ctx.config.data_dir / "save"
    markdown_root = ctx.config.data_dir / "markdown"
    text_files = sorted(save_dir.glob("*.text"))
    if args.bvid:
        text_files = [path for path in text_files if args.bvid in path.name]
    if args.limit:
        text_files = text_files[: int(args.limit)]

    succeeded = 0
    failed = 0
    for text_file in text_files:
        try:
            result = render_or_update_summary(text_file, markdown_root, ai, logger)
            if result:
                logger.info("已修复总结: %s", result[0])
                succeeded += 1
        except Exception as exc:
            logger.error("为 %s 修复总结失败: %s", text_file, format_api_error(exc))
            failed += 1
    _sync_netdisk_best_effort(ctx, logger)
    logger.info("修复总结汇总: 成功=%s 失败=%s", succeeded, failed)
    return 0 if failed == 0 else 1


def _download_audio_impl(ctx: CommandContext, args, logger: logging.Logger, *, upload: bool) -> int:
    task = _task_from_video_arg(ctx, args.video, logger)
    if not task:
        return 1
    audio = AudioService(ctx.config, logger)
    files = audio.download_task_audio(task)
    if upload:
        return 0 if audio.upload_task_audio(task, files) else 1
    for f in files:
        logger.info("已下载音频: %s", f)
    return 0


def download_audio(ctx: CommandContext, args, logger: logging.Logger) -> int:
    return _download_audio_impl(ctx, args, logger, upload=False)


def download_audio_upload(ctx: CommandContext, args, logger: logging.Logger) -> int:
    return _download_audio_impl(ctx, args, logger, upload=True)


def resummarize(ctx: CommandContext, args, logger: logging.Logger) -> int:
    save_dir = ctx.config.data_dir / "save"
    text_files = [path for path in save_dir.glob("*.text") if args.bvid in path.name]
    if not text_files:
        logger.error("未找到 BVID %s 的文稿", args.bvid)
        return 1
    text_file = text_files[0]
    markdown_root = ctx.config.data_dir / "markdown"
    ai = AIService(ctx.config, logger)
    try:
        result = render_or_update_summary(text_file, markdown_root, ai, logger, force=True)
        if result:
            logger.info("已重新生成 Markdown: %s", result[0])
    except Exception as exc:
        logger.error("AI 重新总结失败: %s", format_api_error(exc))
        return 1
    _sync_netdisk_best_effort(ctx, logger)
    return 0


def _sync_netdisk_best_effort(ctx: CommandContext, logger: logging.Logger) -> None:
    try:
        service = ctx.netdisk_sync(logger)
        stats = service.sync(force=True)
        logger.info("更新总结后的网盘同步状态: %s", stats)
    except Exception as exc:
        logger.warning("更新总结后的网盘同步被跳过或失败: %s", exc)


def _task_from_video_arg(ctx: CommandContext, value: str, logger: logging.Logger) -> Task | None:
    bvid, aid = parse_video_input(value)
    if not bvid and aid is None:
        logger.error("无法解析视频输入参数: %s", value)
        return None
    service = BilibiliService(ctx.config, logger)
    if not service.login():
        logger.error("Bilibili 登录失败")
        return None
    info = service.get_video_detail(bvid=bvid, aid=aid)
    info.setdefault("aid", aid)
    return Task.from_bilibili_info(info)


def status(ctx: CommandContext, args, logger: logging.Logger) -> int:
    try:
        queue = ctx.queue(logger, sync=True)
    except Exception as exc:
        logger.warning("同步远程队列仓库失败，将使用本地缓存数据：%s", exc)
        queue = ctx.queue(logger, sync=False)

    pending_tasks: list[Task] = []
    claimed_tasks: list[Task] = []
    results_tasks: list[Task] = []
    done_tasks: list[Task] = []
    failed_tasks: list[Task] = []

    if queue.pending_dir.exists():
        for p in queue.pending_dir.glob("*.json"):
            try:
                pending_tasks.append(Task.from_file(p))
            except Exception as e:
                logger.warning("解析待处理任务文件失败 %s: %s", p, e)

    if queue.claimed_dir.exists():
        for p in queue.claimed_dir.rglob("*.json"):
            try:
                claimed_tasks.append(Task.from_file(p))
            except Exception as e:
                logger.warning("解析处理中任务文件失败 %s: %s", p, e)

    if queue.results_dir.exists():
        for p in queue.results_dir.rglob("task.json"):
            try:
                results_tasks.append(Task.from_file(p))
            except Exception as e:
                logger.warning("解析完成任务文件失败 %s: %s", p, e)

    if queue.done_dir.exists():
        for p in queue.done_dir.rglob("task.json"):
            try:
                done_tasks.append(Task.from_file(p))
            except Exception as e:
                logger.warning("解析已归档任务文件失败 %s: %s", p, e)

    if queue.failed_dir.exists():
        for p in queue.failed_dir.rglob("task.json"):
            try:
                failed_tasks.append(Task.from_file(p))
            except Exception as e:
                logger.warning("解析失败任务文件失败 %s: %s", p, e)

    # Sort tasks chronologically by creation time
    pending_tasks.sort(key=lambda t: t.created_at or "")
    claimed_tasks.sort(key=lambda t: t.created_at or "")
    results_tasks.sort(key=lambda t: t.created_at or "")
    done_tasks.sort(key=lambda t: t.created_at or "")
    failed_tasks.sort(key=lambda t: t.created_at or "")

    limit = int(args.limit) if args.limit else 10

    counts = {
        "pending": len(pending_tasks),
        "claimed": len(claimed_tasks),
        "results": len(results_tasks),
        "done": len(done_tasks),
        "failed": len(failed_tasks),
    }

    # Print statistics summary table
    print("+----------------------+-------+")
    print("| 任务状态 (Status)    | 数量  |")
    print("+----------------------+-------+")
    for status_name, count in counts.items():
        print(f"| {status_name:<20} | {count:>5} |")
    print("+----------------------+-------+")

    def format_duration(seconds: int) -> str:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def print_category_details(name: str, tasks: list[Task]):
        print(f"\n=== {name.upper()} 任务详情 (显示前 {limit}/{len(tasks)} 条) ===")
        if not tasks:
            print("  (无)")
            return
        
        for idx, task in enumerate(tasks[:limit], 1):
            dur_str = format_duration(task.duration)
            title_truncated = task.title[:30] + "..." if len(task.title) > 30 else task.title
            
            detail_suffix = ""
            if name == "claimed":
                detail_suffix = f" | Claimed by: {task.claimed_by or 'unknown'} at: {task.claimed_at or 'unknown'}"
            elif name == "failed":
                detail_suffix = f" | Failed by: {task.failed_by or 'unknown'} | Error: {task.last_error or 'none'}"
                
            print(f"  {idx}. [{task.bvid}] {title_truncated} ({dur_str}){detail_suffix}")
            
        if len(tasks) > limit:
            print(f"  ... 还有 {len(tasks) - limit} 条任务未列出")

    print_category_details("pending", pending_tasks)
    print_category_details("claimed", claimed_tasks)
    print_category_details("results", results_tasks)
    print_category_details("done", done_tasks)
    print_category_details("failed", failed_tasks)

    # Print Recommended Commands
    print("\n=== 推荐处理命令 (Recommended Commands) ===")
    has_commands = False

    if counts["pending"] > 0:
        print("  * 有待处理的转写任务 (pending)：")
        print("    可以使用以下命令认领并开始执行转写任务：")
        print("    python b2t.py server once")
        print("    python b2t.py server run --server-id <your_server_id>")
        has_commands = True

    if counts["claimed"] > 0:
        print("  * 有正在转写中的任务 (claimed)：")
        print("    如果某些任务超时未完成，可以使用以下命令释放其认领状态重新放入队列：")
        print("    python b2t.py server release-claimed")
        has_commands = True

    if counts["results"] > 0:
        print("  * 有已完成待收集的转写结果 (results)：")
        print("    可以使用以下命令将结果收集并生成 Markdown 总结：")
        print("    python b2t.py client collect")
        print("    python b2t.py client render")
        print("    python b2t.py client sync")
        print("    或者一键运行完整流程：")
        print("    python b2t.py client run")
        has_commands = True

    if counts["failed"] > 0:
        print("  * 有失败的任务 (failed)：")
        has_download_failure = any(
            task.last_error and ("yt-dlp" in task.last_error.lower() or "download" in task.last_error.lower())
            for task in failed_tasks
        )
        if has_download_failure:
            print("    检测到部分任务因音频下载/提取错误失败，可在客户端执行以下命令进行音频准备与自动重试：")
            print("    python b2t.py client prepare-audio")
        print("    也可以使用以下命令手动重新提交指定失败的任务：")
        for task in failed_tasks[:3]:
            print(f"    python b2t.py client resubmit-missing --input queue/failed/{task.task_id}/task.json")
        if len(failed_tasks) > 3:
            print("    ...")
        has_commands = True

    if not has_commands:
        print("  当前队列中没有需要处理的活跃任务。全部完成！")

    return 0
