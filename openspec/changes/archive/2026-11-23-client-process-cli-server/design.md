# Design: client-process-cli-server

## Decision log

<!-- grillspec: depth=standard council=no budget=15 asked=4 -->

### Open

### Settled

- [~] D1 `--server cli` 的账号选择 — **通过必需的 `--account <name>` 参数指定单个 Colab 账号** · user · alternatives: 对配置中所有账号运行 `colab run-all` · reversible: easy · superseded by D4
  > “不要调用colab run-all，而是只用一个账号，需要用参数设定”
- [x] D2 `client process <bvid>` 的流程 — **复用 `client add` 的单视频准备阶段（取详情、建任务、提交、准备音频），再执行 wait → collect → render → sync → finish；不做批量 scan；保留默认分类和 `--category`** · user · alternatives: 仅将视频加入任务而不执行后续流程 · reversible: easy
  > “其他同意”
- [x] D3 账号名称列表的来源 — **复用现有 `b2t.py colab status` 显示的配置/书签账号列表** · user · alternatives: 新增命令扫描 WSL 用户 · reversible: easy
  > “复用列表”
- [x] D4 CLI server 账号策略按命令区分 — **`client run --server cli` 调用 `colab run-all`；`client process --server cli` 必须通过 `--account <name>` 指定单个账号** · user · alternatives: 两个命令统一使用多账号或单账号 · reversible: easy
  > “选择 cli 时运行 colab run-all。client process <bvid>也可以使用--server browser|cli选择 cli 时必须通过 --account <name> 指定一个账号”

## Goals

- 为 client run 提供默认 browser 和可选 Colab CLI server 路径。
- 为指定 BV 视频提供不扫描其他视频的完整处理命令。
- 让 process 的 CLI server 使用明确选择的单个账号。

## Non-Goals

- 改变 Colab 账号的配置或发现方式。
- 修改 server 转写流程或 Colab notebook。
- 改变 client add、browser server 或既有 pipeline 步骤的行为。

## Open questions

None.
