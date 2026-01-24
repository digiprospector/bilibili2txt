# Bilibili2txt

将 Bilibili 视频转换为文字记录，并使用 AI 进行智能总结。

## ✨ 功能特性

- 🎬 **自动抓取视频** - 自动抓取 Bilibili 关注分组中 UP 主的最新视频
- 🎤 **语音转文字** - 使用 Faster-Whisper 将视频音频转换为文字
- 🤖 **AI 智能总结** - 支持多个 AI API 并行处理，自动生成投资/股票相关内容分析
- 📝 **Markdown 输出** - 生成格式化的 Markdown 文档，包含视频信息、AI 总结和完整文稿
- ☁️ **网盘同步** - 自动将生成的文档同步到网盘（如坚果云）
- 🔄 **客户端-服务器架构** - 支持本地客户端与远程服务器协作处理

## 📁 项目结构

```
bilibili2txt/
├── client/                 # 客户端脚本
│   ├── scrape.py          # 抓取 Bilibili 视频列表
│   ├── in_queue.py        # 将视频任务放入队列
│   ├── out_queue.py       # 从队列获取处理完成的文本
│   ├── generate_md.py     # 生成 Markdown 文档
│   ├── fix_ai_summary.py  # 为文档添加/修复 AI 总结
│   ├── sync_to_netdisk.py # 同步到网盘
│   ├── check_ai.py        # 检查 AI API 可用性
│   ├── openai_chat.py     # 与 AI 对话
│   └── ...
├── server/                 # 服务器端脚本
│   ├── process_input.py   # 处理视频，提取音频并转录
│   ├── server_in_queue.py # 服务器端队列入口
│   ├── server_out_queue.py# 服务器端队列出口
│   └── server_run.py      # 服务器主程序
├── libs/                   # 共享库
│   ├── ai_utils.py        # AI 工具函数
│   ├── dp_bilibili_api.py # Bilibili API 封装
│   ├── git_utils.py       # Git 操作工具
│   ├── md_utils.py        # Markdown 处理工具
│   ├── webdav.py          # WebDAV 操作工具
│   └── ...
├── config.py              # 配置文件（需从 config_sample.py 复制）
├── config_sample.py       # 配置文件示例
└── tests/                 # 测试脚本
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

复制配置文件并修改：

```bash
cp config_sample.py config.py
```

编辑 `config.py`，配置以下内容：
- Bilibili 关注分组
- WebDAV 账号信息
- AI API Key 和 Base URL
- 网盘目录路径

### 3. 登录 Bilibili

首次使用需要扫码登录：

```bash
python -c "from libs.dp_bilibili_api import DpBilibili; DpBilibili().login()"
```

### 4. 运行

**客户端模式（本地）：**

```bash
# 运行完整流程（抓取 -> 入队 -> 同步）
python client/run_1st.py

# 或分步运行
python client/scrape.py         # 抓取视频列表
python client/in_queue.py       # 放入队列
python client/out_queue.py      # 获取处理结果
python client/generate_md.py    # 生成 Markdown
python client/fix_ai_summary.py # 添加 AI 总结
python client/sync_to_netdisk.py # 同步到网盘
```

**服务器模式（Google Colab）：**

```bash
python server/server_run.py
```

## 🔧 常用命令

```bash
# 检查 AI API 可用性
python client/check_ai.py -l     # 列出所有 AI 配置
python client/check_ai.py        # 测试所有 AI
python client/check_ai.py -n xxx # 测试指定 AI

# 与 AI 对话
python client/openai_chat.py

# 同步 Markdown 到网盘
python client/sync_to_netdisk.py -f  # 强制覆盖

# 清理 WebDAV 文件
python client/clean_webdav.py
```

## ⚙️ 配置说明

### AI 配置

支持配置多个 AI API，程序会自动并行调用：

```python
"open_ai_list": [
    {
        "openai_api_name": "example",      # 配置名称
        "openai_api_key": "sk-xxx",        # API Key
        "openai_base_url": "https://...",  # API Base URL
        "openai_model": "gpt-3.5-turbo",   # 模型名称
        "interval": "12"                   # 请求间隔（秒）
    }
]
```

### WebDAV 配置

用于客户端与服务器之间传输大文件：

```python
"webdav_url": "https://your-server.com/dav/",
"webdav_username": "your_username",
"webdav_password": "your_password"
```

## 📄 License

MIT License
