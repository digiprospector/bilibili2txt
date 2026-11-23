# client-process-cli-server — plan

## Goal

给客户端流水线增加 browser/CLI server 选择，并让用户能对指定 BV 视频执行完整处理流程。

## Architecture

CLI 在 client run 与 process 上共享 server 选项；流水线 wait 阶段默认保留 Chrome 与队列轮询，CLI 模式改为调用现有 Colab handler。process 先复用 add 创建和提交单视频任务，再从 wait 阶段继续完整流水线；它的 CLI 路径使用显式指定的单个账号。

**Spec:** openspec/changes/client-process-cli-server/specs/client-process/spec.md

## Global Constraints

- client run 与 client process 的 --server 默认值必须是 browser。
- client run --server cli 必须调用现有 colab run-all。
- client process --server cli 必须要求 --account 并只调用该账号的 colab run。
- client process 不运行批量 scan，沿用 add 的默认分类和 --category。

## Review Focus

1. Colab CLI 返回失败时，流水线必须在 collect 前终止 → task 2.1 测试。
2. 单视频准备阶段失败时，process 不得继续 wait 或处理后续步骤 → task 3.1 测试。

## 1. CLI 参数与注册

- [x] 1.1 注册 server 与 process 参数并锁定 parser 契约 — verify: pyenv exec python -m pytest tests/test_cli_parser.py -q

Covers: CP-1, CP-2, CP-5 · Test: scenario-first

Files: modify bilibili2txt/cli.py; test tests/test_cli_parser.py

Interfaces:
- Produces: process handler registration with positional bvid, --category, --server browser|cli, and optional --account
- Produces: --server parser argument with choices browser and cli and default browser for client run/process

1. Add parser tests for run and process server defaults, accepted values, process positional BV, category, and account parsing. Update public command-set assertions to match the current CLI, including commands already present before this change. Run tests. Expected: FAIL for the new contract.
2. Register client process and shared server argument specs; preserve all existing run options.
3. Run pyenv exec python -m pytest tests/test_cli_parser.py -q. Expected: PASS.

## 2. Server dispatch in the pipeline

- [x] 2.1 Route the wait phase to browser or the selected Colab CLI handler — verify: focused server-mode tests pass

Covers: CP-1, CP-2, CP-5, CP-7 · Test: scenario-first

Files: modify bilibili2txt/commands/client.py; test tests/test_client_server_modes.py

Interfaces:
- Produces: run_pipeline(ctx, args, logger, from_step=None, server_scope="all") -> int, where server_scope selects colab run-all or single-account colab run when args.server is cli

1. Add tests proving browser mode retains Chrome open/wait/close and CLI run mode calls colab run-all without opening Chrome; assert a nonzero Colab result stops before collect. Run tests. Expected: FAIL.
2. Add the server_scope parameter to run_pipeline and dispatch CLI wait to existing colab.run_all for scope all or colab.run for scope single; keep browser wait behavior unchanged.
3. Run the focused server-mode tests. Expected: PASS for browser default, run-all, selected single-account dispatch, and CLI failure propagation.

## 3. Single-video process workflow and docs

- [x] 3.1 Implement process orchestration and document usage — verify: focused process and full test suites pass

Covers: CP-3, CP-4, CP-6, CP-8 · Test: scenario-first

Files: modify bilibili2txt/commands/client.py, bilibili2txt/cli.py, README.md; create tests/test_client_process.py; test account-name output in tests/test_client_server_modes.py

Interfaces:
- Consumes: add(ctx, args, logger) -> int for task creation/submission/audio preparation
- Consumes: run_pipeline(ctx, args, logger, from_step="wait", server_scope="single") -> int for remaining process workflow
- Produces: process(ctx, args, logger) -> int; args.bvid is the positional input, args.category defaults to 投资, args.server defaults to browser, and args.account is required when args.server is cli

1. Add tests that process validates a BV input through the existing add behavior, uses the requested category, skips scan, starts remaining work at wait, requires account for CLI mode, and passes the account to the single-account server path. Add a characterization test that colab status output includes configured/bookmark account names. Run tests. Expected: FAIL.
2. Implement process: validate --account when server is cli, call add and return immediately on preparation failure, then invoke run_pipeline from wait with single-account scope. Preserve add's category validation and default.
3. Add README examples for client run --server cli, client process BVxxxx, process CLI with --account, and colab status account-name discovery.
4. Run focused process/parser/server tests. Expected: PASS.
5. Run pyenv exec python -m compileall -q bilibili2txt b2t.py tests and pyenv exec python -m pytest -q -p no:cacheprovider using a fresh --basetemp directory outside the repository. Expected: only known baseline parser failures may remain until task 1 updates their assertions; final result must have zero failures.
