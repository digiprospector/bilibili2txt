# bilibili2txt

把 Bilibili 视频转成转写文本，并用 AI 生成 Markdown 总结。

项目现在使用统一 CLI：

```bash
python b2t.py <client|server|admin|init> <command>
```

## 架构

本项目按三类仓库协作：

- 代码仓库：保存源码、测试、示例配置和 Colab notebook。
- `data/`：独立 private 仓库，保存本地数据库、cookie、转写结果、Markdown、任务归档和真实配置。
- `queue/`：独立 Git 仓库，保存 client/server 共享任务队列。

`server` 不使用数据库，只通过 `queue/` 的 JSON 任务和 WebDAV 音频缓存工作。

## 快速开始

1. **安装依赖**：

   ```bash
   pip install -r requirements.txt
   ```

2. **初始化仓库**：

   ```bash
   # 初始化数据仓库（创建目录结构、复制默认配置、初始化 SQLite 数据库）
   python b2t.py init data

   # 初始化任务队列仓库（创建队列目录结构）
   python b2t.py init queue
   ```

   *提示：如果对应的文件夹还不是 Git 仓库，执行时会提示输入 Git Remote URL 并执行 `git init`；如果已存在仓库，会要求输入确认指令以进行清空与重新初始化。*

3. **配置密钥**：

   编辑 `data/config.yaml`，填入对应配置。真实密钥建议放在环境变量或 `data/.env` 中，不要提交到代码仓库。

## 服务器配置

服务器使用colab，可以多个账号同时运行，以提高效率。
服务器上需要有fastest-whisper-XXL, github的key文件。因为需要把github的key文件放在服务器上，我选择用一个小号，专门生成queue的仓库。

1. **faster-whisper-XXL**
访问 https://github.com/Purfview/whisper-standalone-win/releases/tag/Faster-Whisper-XXL, 看到linux版本的包, 复制下载链接
回到colab的终端, 运行

```sh
cd /content/drive/MyDrive/
rm -rf Faster-Whisper-XXL
#下面的地址换成最新版的
wget https://github.com/Purfview/whisper-standalone-win/releases/download/Faster-Whisper-XXL/Faster-Whisper-XXL_r245.4_linux.7z
#如果没有7z程序安装一下
apt install p7zip-full
#解压
7z x Faster-Whisper-XXL_r245.4_linux.7z
#删除压缩包
rm Faster-Whisper-XXL_r245.4_linux.7z license.txt
```

2. **clone代码**

```sh
mkdir -p /content/drive/MyDrive/github
cd /content/drive/MyDrive/github
git clone https://github.com/digiprospector/bilibili2txt.git
cd bilibili2txt/
git submodule init
git submodule update
```
3. **github的key文件**

key文件放到
/content/drive/MyDrive/小号_id_ed25519_github

4. **复制colab notebook**

```sh
cp /content/drive/MyDrive/github/bilibili2txt/notebooks/bilibili2txt_server_colab.ipynb /content/drive/MyDrive/Colab Notebooks/bilibili2txt_server_colab.ipynb
```

5. **修改config.yaml**

```sh
cp config_example.yaml config.yaml
```
修改config.yaml中的server_id，这个是用于区分server的字符串。
  
6. **打开colab的网站**

打开/content/drive/MyDrive/Colab Notebooks/bilibili2txt_server_colab.ipynb文件，运行

## 常用命令

初始化（首次运行或重新初始化）：

```bash
python b2t.py init data
python b2t.py init queue
```

Client 本地流程：

```bash
# 扫描关注的 UP 主
python b2t.py client scan

# 手动直接添加单个视频（扫描、提交、准备音频一步完成）
python b2t.py client add BVxxxx

# 提取视频音频并上传至共享 WebDAV 网盘
python b2t.py client prepare-audio

# 将新视频打包成转写任务提交到 Git 任务队列中
python b2t.py client submit

# 从任务队列拉取已转写完成的 JSON 结果
python b2t.py client collect

# 将收集到的转写结果渲染并调用 AI 生成 Markdown 总结
python b2t.py client render

# 同步生成的 Markdown 总结
python b2t.py client sync

# 提交并推送本地 data 数据仓库中的所有更改
python b2t.py client finish
```

一键本地流程：

```bash
# 一键自动运行完整流程（默认等待转写完成并渲染归档）
python b2t.py client run

# 仅提交任务并立即退出（不等待）
python b2t.py client run --no-wait

# 从某个步骤继续执行后续所有步骤（如从收集开始执行 collect -> render -> sync -> finish）
python b2t.py client resume collect

# 从渲染总结步骤继续执行（render -> sync -> finish）
python b2t.py client resume render
```

Server 远程转写节点：

```bash
python b2t.py server run --server-id colab-a
```

Colab 多账号管理（client 端通过 WSL 调用 `google-colab-cli`）：

```bash
# 为账号执行 OAuth 登录
python b2t.py colab login --account account-a

# 用单个账号启动 session 并运行 notebook
python b2t.py colab run --account account-a

# 并发启动配置中的所有账号
python b2t.py colab run-all

# 查看 session 状态
python b2t.py colab status

# 停止指定账号的 session
python b2t.py colab stop --account account-a
```

每个账号对应 WSL 里的一个用户名，命令通过 `wsl.exe -u <name>` 切换用户执行，
因此各账号的 `$HOME`、colab-cli 登录状态和 session 彼此隔离。账号列表优先读取
`colab.accounts`（见 `config.example.yaml`），未配置时回退到
`colab.bookmark_config` 中的 profile 名称。代理统一读取 `client.proxy`；
`colab.command_timeout_seconds` 控制 `new`/`status`/`stop`/`whoami` 的超时
（默认 30 秒，notebook 执行不限制）。

每个 WSL 用户下只使用一个固定 session 名 `b2t`，`run`/`status`/`stop`/`login`
都操作同一个 session，账号差异完全由 `wsl.exe -u` 的用户身份区分。

Colab:

```text
notebooks/bilibili2txt_server_colab.ipynb
```

Admin:

```bash
python b2t.py admin check-missing
python b2t.py client resubmit-missing
python b2t.py admin check-ai --list
python b2t.py admin fix-summaries
python b2t.py admin resummarize --bvid BVxxxx
python b2t.py admin webdav-clean --dry-run
python b2t.py admin webdav-upload path\to\file.mp3
python b2t.py admin download-audio BVxxxx
python b2t.py admin download-audio-upload BVxxxx
python b2t.py admin push-data
```

## 队列结构

`queue/` 仓库使用一个任务一个 JSON 文件：

```text
queue/
  pending/
  claimed/<server_id>/
  results/<task_id>/
  done/<task_id>/
  failed/<task_id>/
```

server 领取任务时优先选择 `duration` 最大的任务。失败任务会按规则归还 `pending/` 或进入 `failed/`。

## 数据库

client 使用新的 SQLite：

```text
data/bilibili2txt.db
```

主要表：

- `videos`
- `tasks`
- `rendered_files`

数据库只作为 client/admin 本地索引，不作为分布式状态中心。

## 测试

```bash
python -m compileall -q bilibili2txt b2t.py tests
python -m pytest tests\test_new_queue.py tests\test_netdisk_sync.py -q --basetemp .pytest-tmp
```

Windows 上如果默认 pytest temp 目录权限异常，使用 `--basetemp .pytest-tmp`。

## License

MIT License
