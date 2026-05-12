# V1.5-C5B Multica Integration Research

## 1. 背景

小黄已经完成 Agent Handoff 草稿生成、Agent 完成报告审查、打开目标项目终端与复制提示词等能力。原计划的下一步是 V1.5-C5A Whitelisted Agent Launcher，但本机已经部署并运行 Multica。Multica 已经提供本地 Agent runtime、daemon、issue、assign、runs、run-messages 等能力。

因此 C5B 的结论是：小黄不应该自己实现低配 Agent runtime。小黄应该继续承担个人数据库增强、中文自然语言入口、任务理解、目标项目路径识别、handoff prompt 生成、验收总结和任务记忆；Agent 运行、分配、执行记录和消息流应交给 Multica。

## 2. 本机 Multica 状态

本机只运行了低风险只读/帮助命令，没有创建 issue、没有 assign、没有启动 Agent。

确认结果：

```text
where.exe multica
C:\Users\29468\.multica\bin\multica.exe

multica version
multica 0.2.16 (commit: f7fe0829, built: 2026-04-24T07:14:37Z)
go: go1.26.1, os/arch: windows/amd64

multica daemon status
Daemon:      running (pid 14692, uptime 8m39s)
Agents:      claude, codex, opencode, openclaw
Workspaces:  1
```

`multica agent list --output json` 可用，返回 4 个本地 workspace agent，状态均为 idle：

| name | runtime_mode | visibility | status |
| --- | --- | --- | --- |
| Atlas | local | workspace | idle |
| Codex | local | private | idle |
| claude code | local | private | idle |
| open code | local | private | idle |

`multica workspace list` 可用，当前 workspace 为：

```text
ID                                    NAME
1a515996-43f3-4029-bea4-57e4257735f9  hhh-ai-lab
```

注意：`multica workspace list --output json` 在 0.2.16 上报错 `unknown flag: --output`。后续只读 helper 不能假设所有 Multica list 命令都有 JSON 输出。

## 3. CLI 能力摘要

确认过的 issue 相关命令：

- `multica issue create --title ... --description ... --assignee ... --attachment ... --project ... --priority ... --status ... --output json`
- `multica issue assign <id> --to ... --unassign --output json`
- `multica issue runs <issue-id> --output json|table`
- `multica issue run-messages <task-id> --output json --since <int>`
- `multica issue list --limit ... --offset ... --assignee ... --status ... --priority ... --project ... --output json|table`
- `multica issue get <id> --output json`
- `multica issue update <id> --title ... --description ... --assignee ... --status ... --priority ... --project ... --output json`
- `multica issue status <id> <status> --output json|table`
- `multica issue rerun <id> --output json`

对小黄最有价值的最小命令集合是：

- 只读状态：`multica version`、`multica daemon status`、`multica agent list --output json`
- 草稿后创建：`multica issue create --title ... --description ... --output json`
- 分配：`multica issue assign <id> --to <agent> --output json`
- 执行读取：`multica issue runs <issue-id> --output json`
- 消息读取：`multica issue run-messages <task-id> --output json --since <seq>`

`issue create`、`issue assign`、`issue status`、`issue update`、`issue rerun` 都会改变 Multica 状态，必须走用户二次确认。

## 4. 小黄与 Multica 的边界

小黄负责：

- 个人数据库和本地项目记忆的读取与规则转译。
- 中文语音/文本入口和自然语言任务理解。
- 目标项目路径、项目类型、与小黄关系的识别。
- 生成数据库增强的 Agent Handoff prompt。
- 展示目标项目路径、数据库 brief 状态、prompt 预览和安全边界。
- 生成 Multica issue draft，但不默认创建。
- 读取 Multica runs / run-messages 后做中文验收摘要。
- 把 issue id、run id、验收结论和后续建议写入小黄任务历史。

Multica 负责：

- Agent runtime / daemon。
- issue 存储、状态与分配。
- Agent 执行队列。
- runs / run-messages / 多 Agent 执行记录。
- 与 claude、codex、opencode、openclaw 等实际执行器的集成。

边界原则：小黄不要绕开 Multica 直接启动 Claude/Codex/opencode/OpenClaw，也不要复制 Multica 的 issue/task/run 模型做一套低配系统。

## 5. 推荐架构

推荐链路：

```text
用户自然语言需求
-> 小黄 text_task_intent_service 识别为 Agent Handoff
-> 小黄 agent_handoff 生成完整任务包
-> 小黄展示目标项目路径 / 数据库 brief / prompt 预览
-> 小黄生成 Multica issue draft
-> 用户二次确认
-> 小黄执行 multica issue create --title ... --description ... --output json
-> 小黄记录 issue id
-> 用户二次确认后可执行 multica issue assign <id> --to <agent> --output json
-> Multica 管理执行
-> 小黄只读 multica issue runs / run-messages
-> 小黄 agent_review 生成验收摘要
-> 小黄写入 task history
```

必须新增一个模块化窄适配层，而不是把 Multica subprocess 调用散落到 `control_panel_web_service.py`、`text_task_execution_service.py`、`agent_handoff/service.py` 或 `agent_review/service.py`：

```text
src/xiaohuang/multica_integration/
  __init__.py
  models.py
  cli_client.py
  status_service.py
  issue_draft_service.py
  issue_create_service.py
  run_reader_service.py
  safety.py
```

模块职责：

- `cli_client.py`：只负责安全调用 Multica CLI，统一处理 `subprocess.run`、timeout、encoding、JSON 解析、错误码和结构化返回；禁止 `shell=True`；禁止执行未登记命令。
- `models.py`：定义 `MulticaStatus`、`MulticaIssueDraft`、`MulticaIssueCreateResult`、`MulticaRunSummary`、`MulticaMessage` 等数据模型。
- `status_service.py`：只读查询 Multica 状态，不创建 issue，不 assign，不启动 Agent。
- `issue_draft_service.py`：只把小黄 `agent_handoff` 结果转换成 Multica issue draft；不创建 issue，不启动 Agent，不修改任何项目。
- `issue_create_service.py`：后续阶段再做；必须用户二次确认后才允许执行 `multica issue create`；C5B 不实现真实创建。
- `run_reader_service.py`：后续阶段再做；只读 `multica issue runs` / `run-messages`，用于小黄验收报告。
- `safety.py`：集中管理允许的 Multica 子命令、禁止命令、确认策略、secret redaction 和 `E:\DataBase` 禁写边界。

上层边界：

- `control_panel_web_service.py` 只能做薄 API 包装，把请求转给 `multica_integration` service。
- 前端只能调用后端暴露的安全接口，不能拼接 Multica 命令。
- `text_task_execution_service.py` 只能分发已登记的安全 task type，不能直接写 subprocess 调用。
- `agent_handoff` 只生成任务包和 issue draft 输入，不直接调用 Multica。
- `agent_review` 只审查结果，不负责启动 Agent、创建 issue 或 assign。

其中 `cli_client.py` 应只接受参数列表并使用 `subprocess.run(..., shell=False, timeout=...)`。所有可变更状态的命令必须由上层显式传入 `confirmed=True` 或经过现有 pending task registry。安全判断应该集中在 `safety.py`，不能分散为多个模块里的硬编码字符串判断。

## 6. 最小集成方案

### C5C: Multica Readonly Status Panel

只做只读状态卡片，不创建 issue，不 assign。

允许命令：

- `multica version`
- `multica daemon status`
- `multica agent list --output json`
- 目标命令为 `multica workspace list --output json`；但本机 0.2.16 当前不支持该 flag，因此 C5C helper 需要版本兼容：优先尝试登记过的 JSON 命令，失败为 `unknown flag: --output` 时退回只读 `multica workspace list` table 摘要。

输出：

- Multica 是否可用。
- daemon 是否 running。
- daemon 中声明的 agent aliases。
- `agent list` 中的 agent name/status/runtime_mode。
- workspace id/name。

### C5D: Multica Issue Draft Export

小黄基于现有 handoff prompt 生成 issue draft，但只展示，不执行 CLI 创建。

draft 字段：

- title：沿用 handoff title，必要时压缩到短标题。
- description：使用完整 handoff prompt。
- candidate assignee：只作为候选值展示。
- project / priority / status：默认空或用户选择，不猜测。

### C5D.1: Issue Draft Polish

C5D.1 继续保持 draft-only，不创建 issue、不 assign、不启动任何 Agent。修复范围只覆盖草稿质量：

- 目标项目路径在进入 handoff prompt 和 issue draft 前统一规范化，去掉包裹或尾随的引号、中文/英文标点和多余空白，例如 `"E:\Projects\target-app"`、`“E:\Projects\target-app”`、`E:\Projects\target-app。`、`E:\Projects\target-app，后续文字` 都应得到 `E:\Projects\target-app`。
- prompt 正文里的 Windows 路径片段也会做同样清洗，避免 “用户原始需求” 或 issue description 中继续携带错误引号。
- 对 `实现用户请求的功能`、`完成用户请求`、`按用户要求修改`、`处理这个任务`、`执行任务`、`做一下这个` 等过泛任务描述，不阻断 draft 生成，但必须在 warnings 中提示：`任务描述过于泛，建议在创建 Multica issue 前补充具体需求。`
- Markdown / description 中必须附加英文质量提示：`This draft may be too vague for agent execution. Add concrete acceptance criteria before creating a real Multica issue.`

C5D.1 不新增 `issue_create_service.py` 的真实创建逻辑，不新增 assign/run/runs/run-messages 入口，不修改外部项目，也不读取或写入 `E:\DataBase`。

### C5E: Multica Issue Create with Explicit Confirmation

在用户查看 draft 后，必须输入确认短语 `CREATE_MULTICA_ISSUE` 并触发二次确认，才允许执行真实创建：

```powershell
multica issue create --title <title> --description <handoff_prompt> --output json
```

C5E 默认不传 `--assignee`。创建 issue 不等于 assign Agent，也不启动 Claude/Codex/opencode/OpenClaw；C5F 再通过独立二次确认处理 assign。

模块边界：

- `issue_create_service.py` 只负责 confirmed issue create。
- `safety.py` 保持普通 `issue_create` blocked，只允许 `confirmed_issue_create` 通过专用 confirmation gate 和结构化 argv builder。
- `cli_client.py` 只执行由安全层构造并校验过的参数列表，继续使用 `shell=False`、timeout、stdout/stderr 限长和 secret redaction。
- `control_panel_web_service.py` 只做薄 API 包装，不直接调用 subprocess，不拼 Multica 命令。
- 前端只收集用户确认短语并传 title/description，不允许传 argv。

创建成功后只记录：

- issue id
- title
- status
- raw summary
- 未分配 Agent warning

### C5E.1: Target Project Classification Regression Fix

C5E.1 修复 Agent Handoff 的目标项目分类回归，不改真实 issue 创建流程。显式 Windows target path 应优先于“小黄项目”否定边界文本：

- 如果目标路径是 `E:\Projects\xiaohuang` 本体，才按 `target_project_kind=xiaohuang` 处理。
- 如果目标路径是其他 Windows 项目路径，例如 `E:\Projects\target-app`，即使用户同时写了“不修改小黄项目”“不要修改 E:\Projects\xiaohuang”“这个任务和小黄项目无关”“不是小黄项目”，也必须按外部项目处理。
- 这些否定语义表示安全边界，不表示目标项目，因此 `project_relation=unrelated_to_xiaohuang`。
- C5E.1 不执行 `multica issue create`，不 assign，不启动 Agent，不读取 runs/run-messages，不修改外部项目或 `E:\DataBase`。

### C5F: Multica Assign Agent with Explicit Confirmation

在用户确认 issue id 和 agent 后，必须输入绑定两者的确认短语 `ASSIGN <issue_id> TO <agent>`，才允许执行：

```powershell
multica issue assign <id> --to <agent> --output json
```

assign 不是默认动作，不跟 issue draft 或 issue create 隐式绑定。允许 agent 仅限 `claude`、`codex`、`opencode`、`openclaw`。前端只传结构化字段，不能传 argv。

模块边界：

- `issue_assign_service.py` 只负责 confirmed issue assign。
- `safety.py` 保持普通 `issue_assign` blocked，只允许 `confirmed_issue_assign` 通过专用 confirmation gate、issue id 格式校验、agent 白名单和固定 argv builder。
- `cli_client.py` 继续通过 `run_multica_argv()` 执行安全层已验证的参数列表，使用 `shell=False`、timeout、stdout/stderr 限长和 secret redaction。
- `control_panel_web_service.py` 只做薄 API 包装，不直接调用 subprocess，不拼 Multica 命令。
- assign 成功后小黄不调用 `runs` / `run-messages` / `rerun`，不额外启动本地 Agent。

### C6: Read Runs / Run Messages and Review

只读执行记录：

```powershell
multica issue runs <issue-id> --output json
multica issue run-messages <task-id> --output json --since <seq>
```

小黄把 runs / messages 压缩为验收材料，然后复用 `agent_review` 生成中文验收摘要。读取消息时需要设定最大条数、最大字节数和 secret redaction。

## 7. 安全边界

必须二次确认的命令：

- `multica issue create`
- `multica issue assign`
- `multica issue status`
- `multica issue update`
- `multica issue rerun`
- `multica daemon restart`
- 任何会启动、停止、重新排队或改变 Multica 状态的命令

默认禁止：

- 自动启动 Claude/Codex/opencode/OpenClaw。
- 自动粘贴 prompt 到外部终端。
- 绕过 Multica daemon/runtime 直接运行 agent 二进制。
- 把 secret、token、API key 或本地私有路径写入 issue description。
- 修改 `E:\DataBase`。
- 修改外部项目。
- 在没有用户确认的情况下把 handoff prompt 发给 Agent 执行。

实现约束：

- subprocess 必须使用参数列表，禁止 `shell=True`。
- 每个命令必须设置 timeout。
- Multica 允许/禁止命令表必须集中在 `multica_integration/safety.py`。
- `daemon restart` / `daemon stop` 默认禁止。
- `issue create` / `issue assign` 默认禁止，除非调用方提供明确确认信号并通过 pending task safety gate。
- 禁止传入任意 shell command；CLI client 只能接收预登记的 Multica argv 模板和参数字段。
- stdout/stderr 入库前必须限制长度并做敏感字段脱敏。
- `description` 使用小黄生成的 handoff prompt，但要先经过 secret redaction。
- 失败时返回结构化错误，不把完整 stderr 直接展示给用户。
- task history 只保存 issue/run 摘要，不保存完整 run-messages 原文。
- 禁止读取或保存 secret；禁止修改 `E:\DataBase`。

## 8. 不建议现在做的事情

- 不要继续做 C5A Whitelisted Agent Launcher 作为主要路线；会和 Multica runtime 重叠。
- 不要新增大型 `agent_execution` 子系统。
- 不要把 control panel 做成 Multica 的完整替代 UI。
- 不要在 C5B 阶段创建真实 issue 或 assign Agent。
- 不要把 `open_agent_handoff_terminal` 扩展成启动 Agent 或自动粘贴 prompt。
- 不要在 `text_task_execution_service.py` 中直接堆 Multica 执行逻辑；应先建窄 service。
- 不要在 `control_panel_web_service.py`、`agent_handoff/service.py` 或 `agent_review/service.py` 里写死 Multica CLI 调用。
- 不要依赖 `workspace list --output json`，当前版本不支持。

## 9. 后续阶段计划

| phase | name | scope | state-changing |
| --- | --- | --- | --- |
| C5B | Multica Integration Research | 文档、边界、低风险 CLI 确认 | 否 |
| C5C | Multica Readonly Status Panel | 只读状态 helper + 控制面板状态展示 | 否 |
| C5D | Multica Issue Draft Export | 从 handoff 生成 issue draft | 否 |
| C5E | Multica Issue Create with Explicit Confirmation | 二次确认后创建 issue | 是 |
| C5F | Multica Assign Agent with Explicit Confirmation | 二次确认后 assign | 是 |
| C6 | Multica Runs Review | 只读 runs / run-messages，生成验收报告 | 否 |

## 10. C5B 结论

小黄后续应该通过 Multica CLI 创建 issue、分配 Agent、读取运行记录，但不应该把这些动作合并成无确认的自动执行链路。

最小接入应从只读状态开始，再做 issue draft。只有当用户明确确认 issue 内容、目标项目路径、assignee 和风险边界后，才允许调用 `issue create` 或 `issue assign`。

## 11. C5C Readonly Status Panel Implementation

C5C 已按模块化边界实现只读状态面板：

```text
src/xiaohuang/multica_integration/
  __init__.py
  models.py
  safety.py
  cli_client.py
  status_service.py
```

职责保持如下：

- `safety.py` 集中登记只读命令白名单和危险命令黑名单。
- `cli_client.py` 只接受 command key，不接受前端或上层传入 argv；使用 `subprocess.run` 参数列表、`shell=False`、timeout、stdout/stderr 限长和基础 secret redaction。
- `status_service.py` 聚合 `version`、`daemon_status`、`agent_list_json`、`workspace_list_json`，并在本机 0.2.16 不支持 `workspace list --output json` 时 fallback 到 `workspace_list_table`。
- `control_panel_web_service.py` 只新增薄 API `get_multica_status()`，不直接调用 subprocess。
- 前端只新增“Multica 状态”卡片和“刷新 Multica 状态”按钮，不提供 issue create、assign、runs、run-messages、启动 Agent 或命令输入。

C5C 允许的命令保持为：

```text
version
daemon_status
agent_list_json
workspace_list_json
workspace_list_table
```

C5C 仍禁止：

```text
issue_create
issue_assign
issue_status
issue_update
issue_rerun
issue_runs
issue_run_messages
daemon_restart
daemon_stop
agent_launch
```

真实只读后端验收结果显示：

```text
installed=True
version=multica 0.2.16
daemon_running=True
agents=openclaw, claude, codex, opencode
workspace_summary=1 workspace(s): ... hhh-ai-lab
warning=workspace list --output json unsupported; fallback to table output
```

## 12. C5D Multica Issue Draft Export

C5D 在 C5C 的模块化边界上新增通用 Issue 草稿导出能力。它适用于用户任意 Agent Handoff，不绑定某个业务方向或前端示例。

新增模块：

```text
src/xiaohuang/multica_integration/issue_draft_service.py
```

扩展模型：

```text
MulticaIssueDraft
```

职责边界：

- `issue_draft_service.py` 只把小黄生成的 Agent Handoff 转换成 Multica issue draft。
- `control_panel_web_service.py` 只提供薄 API `build_multica_issue_draft()`。
- 前端只展示草稿、复制文本、下载 Markdown Blob。
- 本阶段不执行 `multica issue create`，不 assign Agent，不读取 runs / run-messages，不启动任何 Agent。

通用链路：

```text
任意用户需求
-> 小黄生成 Agent Handoff
-> 前端读取完整 handoff prompt
-> build_multica_issue_draft
-> 展示 title / description / target_project_path / suggested_assignees
-> 复制标题、复制描述、复制命令草稿、下载 Markdown 草稿
```

如果用户指定 `E:\Projects\sample-project`，issue draft 会保留该目标项目路径，并在描述中继续强调 target project、project relation、database brief 状态和安全边界。

命令草稿只是文本 preview，例如：

```text
multica issue create --title '<title>' --description '<description or placeholder>' --output json
```

当 description 过长时，命令草稿使用占位描述，并提示用户复制完整 Issue 描述或下载 Markdown 草稿。真实创建留给后续 C5E，在用户二次确认后实现。

安全规则：

- 草稿中必须明确“仅草稿，未创建 issue，未分配 Agent”。
- 标题、描述、命令草稿和 Markdown 都经过基础 secret redaction。
- suggested assignees 只是建议：`claude`, `codex`, `opencode`, `openclaw`。
- preferred agent 未知时默认建议 `claude`，但不自动 assign。
