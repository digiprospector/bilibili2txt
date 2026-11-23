## Why

当前 client run 只支持通过浏览器启动转写服务。用户需要能选择 CLI 管理的 Colab server，并能针对一个指定 BV 号运行完整客户端流程而不扫描其他视频。

## What Changes

- 为 client run 增加 --server browser|cli，默认使用 browser；CLI 模式启动配置中的全部 Colab 账号。
- 新增 client process <bvid>，直接处理指定视频，不运行批量 scan；支持分类和 server 选择。
- process 使用 CLI server 时要求 --account <name>，并复用现有 Colab 账号列表。

## Capabilities

### New Capabilities
- client-process: 选择客户端转写 server，并对指定视频执行完整处理流程。

### Modified Capabilities

None.

## Impact

影响 bilibili2txt/cli.py、bilibili2txt/commands/client.py、client parser/流程测试和 README。CLI server 通过已合并的 bilibili2txt.commands.colab 能力运行。