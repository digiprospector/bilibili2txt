# colab-cli-dev 分支开发计划

## 需求背景

当前启动 Colab server 的流程是：client 端使用多个不同的浏览器 profile，
每个 profile 登录一个不同的 Google 账号，分别打开 Colab 并手动运行
`notebooks/bilibili2txt_server_colab.ipynb`，从而启动多个 server 转写节点。

目标是改用 `colab-cli` 取代这些浏览器 profile 的手动操作：

- 在 client 端直接运行 colab-cli 命令。
- colab-cli 必须支持多个 Google 账号同时登录。
- 每个账号独立打开/运行同一个 notebook，互不干扰。

## 开发原则

**手动操作优先，代码后补**：在引入 colab-cli 的每个阶段，必须先由开发方
提供详细的手动操作步骤，由用户手动执行并确认成功后，才能将该步骤固化到
代码中。开发过程中不自行运行 colab-cli 或 Colab 相关命令。

## 开发计划

### 1. WSL 环境准备（手动验证）

google-colab-cli 只支持 Linux/macOS，client 端是 Windows，通过 WSL 运行。

**用户手动操作步骤：**

1. 打开 WSL 终端
2. 安装 google-colab-cli：
   ```bash
   pip install google-colab-cli
   ```
3. 验证安装成功：
   ```bash
   colab version
   ```

用户确认成功后再进入下一步。

### 2. 多账号认证设计

- 为每个 Google 账号建立独立凭据（token/cookie），互不共享。
- 设计配置格式，例如：

```yaml
colab_accounts:
  - name: account-a
    credentials: data/colab/account-a
    server_id: colab-a
  - name: account-b
    credentials: data/colab/account-b
    server_id: colab-b
```

- 提供登录命令，交互式完成每个账号的认证并保存凭据。
- 提供批量运行命令，按配置并发或顺序启动多个账号的 notebook。

### 3. 前置条件

1. **代理设置**：运行 colab 命令前需要设置 `https_proxy` / `http_proxy` 环境变量。代理地址复用 client 配置中已有的 proxy 设置（`webdav.proxy` 或新增独立配置项）。
2. **GPU 模式**：`colab new` 时需要指定 `--gpu T4`（或配置中指定的型号）。
3. **完成后关闭 VM**：notebook 执行完毕后需要执行 `colab stop` 释放 VM 资源。

### 4. CLI 集成

在 `b2t.py` 中新增 `colab` 命令组（或独立脚本，视调研结果决定）：

```bash
# 登录某个账号
python b2t.py colab login --account account-a

# 用单个账号运行 notebook
python b2t.py colab run --account account-a

# 按配置批量运行所有账号
python b2t.py colab run-all

# 查看各账号运行状态
python b2t.py colab status

# 停止某个账号的 notebook
python b2t.py colab stop --account account-a
```

### 5. Notebook 适配

notebook 本身保持 `notebooks/bilibili2txt_server_colab.ipynb` 不变，
但需要确认：

- 每个账号运行时读取自己 `data/config.yaml` 中对应的 `server_id`。
- 各账号使用自己的 SSH key 和 Git 身份。
- 各账号的队列仓库互不冲突。

### 6. 手动验证流程

每个功能点都按以下顺序推进：

1. 开发方提供详细的手动操作步骤。
2. 用户手动执行并确认结果。
3. 用户反馈成功后，开发方才将该操作集成到代码中。
4. 集成后用户再次手动验证，确认代码版本与手动步骤行为一致。

关键验证项：

- 单账号 colab-cli 登录成功。
- 单账号运行 notebook 成功，server 正常领取任务。
- 多账号同时运行，server_id 互不相同，任务互不冲突。
- 停止单个账号不影响其他账号。

### 7. 测试与验证

- 现有测试无回归：

```bash
python -m compileall -q bilibili2txt b2t.py tests
python -m pytest tests/test_new_queue.py tests/test_netdisk_sync.py -q --basetemp .pytest-tmp
```

## 非目标

- 不修改现有 server 转写逻辑。
- 不修改 Git 任务队列模型。
- 不修改 client/admin 其他命令行为。
