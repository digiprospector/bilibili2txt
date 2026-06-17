# bilibili2txt Rewrite Design

## Goal
重写整个项目，但保留现有功能全集，面向多台机器协作运行。

目标不是保留旧脚本结构，而是重建为一个清晰的核心包和统一 CLI：

- `client` 负责抓取、提交、收集、生成 Markdown、同步网盘
- `server` 负责领取、转写、发布结果
- `admin` 负责维护、检查、修复、手工工具

所有命令都必须有完整控制台输出，Colab 也必须能直接看到执行过程。

## Core Principles

- 一个任务一个 JSON 文件，不再使用 JSONL
- 任务优先级由 `duration` 决定，server 优先领取最长任务
- 任务失败必须可归还，claimed 状态必须可回收
- 多机协作只通过 Git 队列和 WebDAV 音频缓存交互
- `data/` 是独立 private 仓库，保存敏感数据、本地数据库和本地产物
- `queue/` 是独立 Git 仓库，保存跨机器任务队列
- 不做旧脚本兼容入口
- 所有命令输出到 stdout，同时写日志文件

## Config

配置使用 YAML：

- `config.example.yaml`
- `config.yaml`，加入 `.gitignore`
- 可选 `.env`

优先级：

`defaults < config.yaml < env vars < CLI flags`

敏感信息不直接写进 YAML，用环境变量名引用。

真实配置优先放在 private `data/` 仓库：

```text
data/config.yaml
data/.env
```

加载顺序：

```text
--config 指定路径
data/config.yaml
config.yaml
config.example.yaml
```

关键配置分组：

- `app`
- `data`
- `queue`
- `bilibili`
- `webdav`
- `client`
- `server`
- `ai`

## Repository Boundaries

项目涉及三个 Git 仓库：

- 代码仓库：当前项目，保存源码、测试、notebook、示例配置
- `data/` 仓库：private，保存本地敏感数据、本地数据库、cookie、转写结果、Markdown、任务归档
- `queue/` 仓库：client/server 共享，保存任务队列状态

命令职责边界：

- `client submit`、`client collect`、`client resubmit-missing`、`server claim`、`server publish`、`server run` 只操作 `queue/` 仓库的 Git 状态
- `admin push-data` 只操作 `data/` 仓库的 Git 状态
- 不使用代码仓库的 Git 状态判断 `data/` 或 `queue/` 是否有变更
- `data/` 和 `queue/` 内容不得被代码仓库提交

## Client Database

client 使用新的 SQLite 数据库：

```text
data/bilibili2txt.db
```

server 不使用数据库。

数据库只作为 client/admin 的本地索引和审计，不作为分布式状态中心。跨机器状态以 `queue/` 中的 JSON 文件为准。

### `videos`

记录 B 站视频基础信息，按 `bvid` 去重。

字段：

- `bvid` primary key
- `aid`
- `cid`
- `title`
- `up_name`
- `up_mid`
- `pubdate`
- `duration`
- `source_url`
- `video_status`
- `first_seen_at`
- `last_seen_at`

### `tasks`

记录 client 本地生成和提交过的任务。

字段：

- `task_id` primary key
- `bvid`
- `task_file`
- `queue_state`
- `attempts`
- `max_attempts`
- `last_error`
- `created_at`
- `submitted_at`
- `completed_at`

### `rendered_files`

记录 Markdown/AI 摘要生成状态。

字段：

- `bvid`
- `text_file`
- `markdown_file`
- `ai_provider`
- `render_status`
- `last_error`
- `rendered_at`

## Queue Model

队列是 Git 仓库内的文件目录，不是数据库。

目录结构：

```text
queue/
  pending/
  claimed/<server_id>/
  results/<task_id>/
  done/<task_id>/
  failed/<task_id>/
```

任务文件格式：

```json
{
  "task_id": "BVxxxx",
  "bvid": "BVxxxx",
  "title": "title",
  "up_name": "up",
  "up_mid": 123,
  "pubdate": 1718500000,
  "duration": 7200,
  "cid": 123,
  "status": "normal",
  "source_url": "https://www.bilibili.com/video/BVxxxx",
  "created_at": "2026-06-16T10:15:30+08:00",
  "attempts": 0,
  "max_attempts": 3,
  "claimed_by": null,
  "claimed_at": null,
  "last_error": null
}
```

文件名规则：

```text
{duration:06d}_{created_at}_{bvid}.json
```

这样 server 可以直接按文件名排序辅助选取最长任务。

## State Flow

正常流转：

`pending -> claimed/<server_id> -> results -> done`

失败流转：

`claimed -> pending`

不可重试失败：

`claimed -> failed`

超时回收：

`claimed/<server_id> -> pending`

## Command Set

统一入口：`b2t`

### client

- `b2t client scan`
- `b2t client submit`
- `b2t client prepare-audio`
- `b2t client collect`
- `b2t client render`
- `b2t client sync`
- `b2t client run`
- `b2t client resubmit-missing`

### server

- `b2t server claim`
- `b2t server transcribe`
- `b2t server publish`
- `b2t server once`
- `b2t server run`

### admin

- `b2t admin check-missing`
- `b2t admin check-ai`
- `b2t admin fix-summaries`
- `b2t admin webdav-clean`
- `b2t admin webdav-upload`
- `b2t admin download-audio`
- `b2t admin download-audio-upload`
- `b2t admin push-data`
- `b2t admin resummarize`

## Colab Notebook

项目需要提供一个 Colab notebook：

```text
notebooks/bilibili2txt_server_colab.ipynb
```

用途：

- 在 Colab 上启动远程 `server` 转写节点
- 让用户不需要手动记忆 server 启动步骤
- 确保所有日志直接显示在 Colab cell 输出里

Notebook 职责：

- 挂载 Google Drive
- 安装系统依赖和 Python 依赖
- 拉取或更新项目代码
- 从 Google Drive 固定路径读取 `config.yaml`
- 检查 faster-whisper-xxl 路径
- 检查 Git 队列可用性
- 检查 WebDAV 可用性
- 检查 B 站 cookie 文件是否存在
- 执行 `b2t server run --server-id <id>`

Notebook 不负责：

- 抓取 B 站任务
- 生成 Markdown
- 同步网盘
- client 侧一键流程

Colab 角色只作为远程 server 转写节点。

Notebook 输出要求：

- 每个步骤有明确标题
- 每个检查项打印成功或失败原因
- `b2t server run` 的 stdout 必须直接显示在 cell 输出中
- 不把日志只写到文件

## Client Commands

### `client scan`

职责：

- 登录 B 站
- 抓取关注分组或指定 UP
- 去重
- 生成单任务 JSON 文件

行为：

- 只负责生成本地任务，不进入 Git 队列
- `duration > scrape_duration_max` 的任务标记为 `too_long`
- 输出到 `temp/tasks/`
- 任务文件名使用 duration 前缀，保证 server 可排序

### `client submit`

职责：

- 把 `temp/tasks/*.json` 提交到 `queue/pending/`

行为：

- 只提交 `status=normal`
- 按 `task_id` 全队列去重
- 成功后把本地任务文件移动到 `data/tasks/submitted/`
- 提交失败则保留本地任务，等待下次重试

### `client prepare-audio`

职责：

- 处理长视频音频预下载并上传 WebDAV
- 支持失败任务重新补音频并放回 pending

行为：

- 可扫描 `temp/tasks/`、`queue/pending/`、`queue/failed/`
- `queue/failed/` 只处理“下载失败/音频获取失败”类任务
- 音频命名：

```text
{bvid}.mp3
{bvid}_1.mp3
{bvid}_2.mp3
```

- 不保留旧命名兼容
- 上传成功后，如果来源是 `failed` 且失败原因属于下载失败，则直接移回 `pending`
- 这一步同时负责恢复队列状态

### `client collect`

职责：

- 从 `queue/results/` 拉取转写结果
- 写入本地 `data/save/`
- 清理对应的 missing 文件

行为：

- 收集成功后把整个 `queue/results/<task_id>/` 移动到 `queue/done/<task_id>/`
- `done/` 保留完整 transcript 和 task.json
- 不删除 transcript 文件
- 如果 `temp/missing_tasks/` 中存在同 `task_id` 或 `bvid` 的文件，收集成功后删除对应 missing 文件

### `client render`

职责：

- 从 `data/save/*.text` 生成 Markdown
- 必须调用 AI 摘要

行为：

- 处理完所有 `.text` 才退出
- 每个 `.text` 依次尝试所有可用 AI
- 任一 AI 成功即可生成 Markdown
- 所有 AI 都失败时，该文件不生成 Markdown，只记日志
- 命令最后如果有失败文件，返回非 0
- 不写失败报告文件
- 下次 render 依靠 Markdown 缺失自动重试失败文件

### `client sync`

职责：

- 把本地 Markdown 同步到网盘目录

规则：

- 如果 Markdown 时间戳属于当前月份，复制到：

```text
{netdisk_dir}/markdown/YYYY-MM/DD/*.md
```

- 如果不是当前月份，复制到：

```text
{netdisk_dir}/markdown/YYYY/MM/DD/*.md
```

- 当月使用 `YYYY-MM`
- 历史月使用 `YYYY/MM`
- 每月 1 号，先把上个月的 `YYYY-MM/DD` 目录移动到 `YYYY/MM/DD`
- 目标冲突时默认跳过，`--force` 覆盖

### `client run`

职责：

- 本地一键流程

默认：

`scan -> prepare-audio -> submit`

加 `--wait`：

`scan -> prepare-audio -> submit -> wait -> collect -> render -> sync`

## Server Commands

### `server claim`

职责：

- 优先恢复当前 `server_id` 自己已 claimed 的任务
- 否则从 pending 中领取最长任务

行为：

- 启动时先检查 `claimed/<server_id>/`
- 如果已有任务，直接返回该任务，不领取新任务
- 否则扫描 `pending/`
- 只领取 `duration <= max_duration_seconds` 的任务
- 选择 duration 最大的任务
- 领取后更新 `attempts/claimed_by/claimed_at`

### `server transcribe`

职责：

- 处理已经 claim 的任务
- 获取音频并转写

行为：

- 音频优先级：

```text
1. WebDAV {bvid}.mp3
2. WebDAV {bvid}_1.mp3, {bvid}_2.mp3 ...
3. yt-dlp 本地下载
```

- 不保留旧 WebDAV 文件命名兼容
- faster-whisper 输出到本地 `temp/server_results/<task_id>/`
- 多 P 结果保留分片输出
- 下载失败、WebDAV 失败、yt-dlp 失败、转写命令失败都视为可重试错误

### `server publish`

职责：

- 发布转写结果或归还失败任务

成功：

- 把本地结果复制到 `queue/results/<task_id>/`
- 删除 `claimed/<server_id>/` 中的任务 JSON
- 提交 Git 队列

失败：

- 可重试失败且 `attempts < max_attempts` 时回到 `pending/`
- 不可重试失败或达到上限时进入 `failed/`
- 保留 `last_error`

### `server once`

职责：

- 单轮执行

顺序：

`claim -> transcribe -> publish`

### `server run`

职责：

- 循环执行 `once`
- 启动时回收超时 claimed 任务

行为：

- `claimed_at` 超过 `claim_timeout_minutes` 的任务回到 `pending`
- 支持 `--max-tasks`
- 支持 `server_id`
- 退出条件：

  - 没有任务
  - 达到 `max_tasks`
  - 控制任务 `quit`
  - 不可恢复错误

## Admin Commands

### `admin check-missing`

职责：

- 只检查本地缺失
- 不检查远端队列状态

行为：

- 对比 `data/tasks/submitted/*.json` 和 `data/save/*.text`
- 找出 `status=normal` 但本地没有 `.text` 的任务
- 输出缺失任务到 `temp/missing_tasks/*.json`
- 不修改队列

### `client resubmit-missing`

职责：

- 把 `temp/missing_tasks/*.json` 重新提交到 `queue/pending/`

行为：

- 如果队列已有同 `task_id`，跳过
- 复制到 `pending/`
- 重置 `attempts/claimed_by/claimed_at/last_error/status`
- 成功后保留本地 missing 文件

### `admin check-ai`

职责：

- 测试 AI provider

行为：

- 支持列出所有 provider
- 支持单个 provider
- 支持股票 prompt 测试
- 不修改配置

### `admin fix-summaries`

职责：

- 批量补齐或修复 AI 摘要

行为：

- 扫描 `data/save/*.text`
- Markdown 缺失或 AI 总结无效时重建
- 对每个文件尝试所有 AI
- 成功后更新本地 Markdown 和网盘 Markdown
- 所有文件处理完才退出

### `admin webdav-clean`

职责：

- 清空 WebDAV 音频缓存

行为：

- 默认直接删除
- `--dry-run` 仅预览

### `admin webdav-upload`

职责：

- 手动上传单文件到 WebDAV

行为：

- 成功后默认删除本地文件
- `--keep` 保留本地文件

### `admin download-audio`

职责：

- 手动下载 B 站音频

行为：

- 只下载不上传
- 支持 URL / BVID / AVID

### `admin download-audio-upload`

职责：

- 手动下载并上传 WebDAV

行为：

- 单 P 上传为 `{bvid}.mp3`
- 多 P 上传为 `{bvid}_1.mp3` 等
- 成功后删除本地音频

### `admin push-data`

职责：

- 提交并推送 `data/` 仓库

行为：

- 没有变更直接返回 0
- push 失败返回非 0，不做无限重试

### `admin resummarize`

职责：

- 针对指定 BVID 重新生成摘要并更新 Markdown/网盘

行为：

- 只处理指定 BVID
- 找不到文稿返回非 0
- AI 失败不修改文件

## Logging

所有命令必须输出全面消息。

标准内容：

- 命令名
- 配置摘要
- 关键目录
- 当前处理对象
- 跳过原因
- 重试次数
- 失败原因
- 最终统计

日志规则：

- stdout 默认 INFO
- 文件日志默认 DEBUG
- Colab 必须能看到完整 stdout

## Module Layout

建议核心包：

```text
bilibili2txt/
  cli.py
  config.py
  database.py
  logging.py
  models.py
  paths.py
  commands/
  services/
    ai.py
    audio.py
    bilibili.py
    gitqueue.py
    gitrepo.py
    markdown.py
    netdisk.py
    transcriber.py
    video_id.py
    webdav.py
```

旧 `client/` 和 `server/` 脚本入口不再保留，所有功能通过 `b2t` CLI 提供。
旧 `libs/` 兼容层不再保留，B 站 API、AI、Git、WebDAV、Markdown 等能力全部迁移到 `bilibili2txt/`。

## Testing

测试重点：

- 配置加载和校验
- 任务文件格式
- pending/claimed/results/done/failed 流转
- longest-first claim
- claim 超时回收
- collect 时删除 missing 文件
- sync 月度目录规则
- render 的“全部 AI 失败后继续下一个文件”行为

外部服务用 mock：

- B 站
- WebDAV
- Git
- OpenAI
- yt-dlp
- faster-whisper

## Non-Goals

- 不保留旧脚本入口兼容
- 不做 HTTP 服务化
- 不做数据库型任务中心
- 不做 JSONL 队列
