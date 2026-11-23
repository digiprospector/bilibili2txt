## Purpose

为客户端流水线提供 browser/CLI server 选择，并允许对一个指定视频执行从准备到归档的完整处理流程。

## ADDED Requirements

### Requirement: Client run server selection
client run SHALL accept --server browser|cli, default to browser, preserve the existing browser behavior by default, and WHEN --server cli is selected, invoke the Colab CLI run-all flow to process the submitted queue before continuing with result collection.

#### Scenario: CP-1 Default server uses browser
- **WHEN** the user runs client run without --server
- **THEN** the client uses the existing browser-based wait behavior

#### Scenario: CP-2 CLI server runs all configured accounts
- **WHEN** the user runs client run --server cli
- **THEN** the client runs the existing Colab run-all flow and continues the pipeline after that flow completes

### Requirement: Process one specified video
client process <bvid> SHALL process only the specified video without running the batch scan step, using the same video detail/task submission/audio preparation behavior as client add, then execute wait, collect, render, sync, and finish; it SHALL accept the same default category and --category option as client add.

#### Scenario: CP-3 Process a single video end to end
- **WHEN** the user runs client process BVxxxx
- **THEN** the client prepares and submits that video and executes the remaining pipeline steps without scanning for other videos

#### Scenario: CP-4 Process uses the requested category
- **WHEN** the user runs client process BVxxxx --category 历史
- **THEN** the created task and generated output use the 历史 category

### Requirement: Process server and account selection
client process SHALL accept --server browser|cli, default to browser, and preserve the existing browser wait behavior by default; WHEN --server cli is selected, it MUST require --account <name> and run the existing Colab CLI flow for that single account. The available account names SHALL be displayed by the existing colab status command using its configured/bookmark account list.

#### Scenario: CP-5 Process defaults to browser
- **WHEN** the user runs client process BVxxxx without --server
- **THEN** the client uses the existing browser-based wait behavior without requiring an account

#### Scenario: CP-6 Process CLI requires one account
- **WHEN** the user runs client process BVxxxx --server cli without --account
- **THEN** argument validation reports that --account is required

#### Scenario: CP-7 Process CLI runs selected account
- **WHEN** the user runs client process BVxxxx --server cli --account account-a
- **THEN** the client runs the Colab CLI flow for account-a and continues the pipeline after it completes

#### Scenario: CP-8 Account names are discoverable
- **WHEN** the user runs colab status without selecting an account
- **THEN** the output displays the account names available from the configured/bookmark account list