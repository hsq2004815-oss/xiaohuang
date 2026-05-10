# V1.5-B0 任务历史与结果沉淀 — 设计文档

## 版本

| 项目 | 值 |
|------|-----|
| 文档版本 | B0（仅设计，无代码实现） |
| 日期 | 2026-05-10 |
| 状态 | 设计完成，待 B1 实现 |

---

## 一、为什么需要任务历史

当前小黄文本任务链路完整：用户输入 → 意图识别 → pending task → registry → 用户确认 → 只读执行 → 结果卡片。但所有执行结果都是瞬时的：

- **前端 `textChatMessages`** — 浏览器内存数组，刷新/重启控制面板后消失。
- **后端 `PendingTextTaskRegistry`** — 任务确认后状态迁移为 completed/blocked/failed，但不持久化结果内容。
- **runtime events** — 记录的是"发生了什么"（操作事件），不是"小黄帮我做了什么，结果是什么"。

用户实际场景：
1. 上午让小黄做了一次健康检查，下午想回看当时的结果。
2. 连续做了几次日志分析和配置摘要，想对比不同时间点的结果。
3. 控制面板重启后，之前确认执行的任务结果全部丢失。

**任务历史的核心目标：让用户能回看"我让小黄做了什么，结果是什么"。**

---

## 二、哪些任务结果应该保存

### B1 保存范围

| 条件 | 是否保存 |
|------|----------|
| confirmed text task，status = `completed` | ✅ 保存 |
| confirmed text task，status = `failed` | ✅ 保存（精简记录） |
| readonly 任务类型（7 种白名单） | ✅ 保存 |
| pending 任务（未确认） | ❌ 不保存 |
| cancelled 任务 | ❌ 不保存 |
| blocked 任务 | ❌ 不保存 |
| 普通聊天消息（非任务） | ❌ 暂不保存 |
| 面板控制命令（启动/停止/重启） | ❌ 不保存（这是 runtime events 的职责） |

### B1 保存的任务类型

```
readonly_log_analysis
readonly_status_check
readonly_diagnostic_review
readonly_recent_errors_review
readonly_runtime_events_review
readonly_config_summary
readonly_health_report
```

### 后续 B2/B3 可扩展

- 下载任务完成结果
- PDF 解析任务结果
- 爬虫/数据采集任务结果
- 数据库查询任务结果
- 自动化任务执行结果

---

## 三、哪些内容绝对不能保存

### 绝对禁止

| 类别 | 说明 |
|------|------|
| API key / token / password / secret | 任何形式，任何字段 |
| authorization header / Bearer token | 完整值或片段 |
| 完整日志原文 | 不保存多行原始日志 |
| 完整 traceback | 最多保存第一行摘要 |
| 完整用户私密文本 | 用户输入全文不保存（只保留任务 title/summary） |
| 大文件内容 | 下载文件、网页全文、PDF 全文 |
| 配置文件原文 | 只保存脱敏摘要，不保存原始 JSON |
| 系统信息 | 不保存环境变量、路径、进程列表等原始系统数据 |

### 默认不保存（B1 暂不考虑）

| 类别 | 说明 |
|------|------|
| 原始 details 全文 | B1 只保存 summary + safe_details_excerpt |
| 完整的 read_files 列表 | 只保存 read_files_count |
| 用户原始输入文本 | 不保存 `original_text` 字段 |

---

## 四、保存在哪里

### 路径推荐

```
data/task_history/task_results.jsonl
```

### 理由

1. **`data/`** — 项目已有此目录（用于 recordings），语义上适合放运行时产生的用户数据。
2. **不要放 `logs/`** — `logs/` 是日志目录，语义不同。任务历史是用户可回看的结果数据，不是运维日志。
3. **不要和 runtime_events 混用** — `logs/runtime_events.jsonl` 是运行事件，可清空。任务历史不应被 runtime events clear 按钮清掉。
4. **不要放源码目录** — `src/` 下只放代码。
5. **Git ignore** — `data/` 已在 `.gitignore` 中，实际运行产生的 task history 文件不会误提交。

### 文件管理

- 单文件 `task_results.jsonl`，每行一条 JSON。
- 文件不存在时首次 append 自动创建。
- 不做分片、不做轮转（B1 数据量极小，后续需要再设计）。
- 不设最大文件大小硬限制，但每条记录 summary 截断保证单行远小于 10KB。

---

## 五、保存什么字段 — JSONL Schema

### B1 完整 schema

```json
{
  "history_id": "taskhist_a1b2c3d4",
  "task_id": "text-task-e5f6g7h8",
  "created_at": "2026-05-10T14:30:00.123456",
  "completed_at": "2026-05-10T14:30:02.654321",
  "task_type": "readonly_health_report",
  "title": "小黄健康检查",
  "status": "completed",
  "ok": true,
  "risk_level": "low",
  "summary": "总体状态：有警告。历史日志中发现 3 条 ERROR 记录，建议排查来源。",
  "safe_details_excerpt": "一、基础状态 — 6/6 正常\n二、配置状态\n  - LLM: 已启用...",
  "source": "chat",
  "read_files_count": 0,
  "result_kind": "readonly_report",
  "tags": ["health", "readonly"],
  "schema_version": 1
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `history_id` | string | ✅ | 唯一标识，格式 `taskhist_<uuid_hex_8>` |
| `task_id` | string | ✅ | 原始 pending task 的 task_id |
| `created_at` | string | ✅ | ISO 8601 时间戳（创建记录的时间） |
| `completed_at` | string | ✅ | ISO 8601 时间戳（任务执行完成的时间） |
| `task_type` | string | ✅ | 只读任务类型（7 种白名单之一） |
| `title` | string | ✅ | 任务标题 |
| `status` | string | ✅ | `completed` 或 `failed` |
| `ok` | boolean | ✅ | 任务是否成功 |
| `risk_level` | string | ✅ | `low` / `medium` / `high` |
| `summary` | string | ✅ | 脱敏后的任务摘要 |
| `safe_details_excerpt` | string | ❌ | 脱敏截断后的详情摘要，最大 500 字 |
| `source` | string | ❌ | 触发来源，当前固定 `"chat"` |
| `read_files_count` | integer | ❌ | 读取的文件数量（数量，不存路径列表） |
| `result_kind` | string | ❌ | 结果类别，如 `readonly_report`，为后续扩展预留 |
| `tags` | array | ❌ | 标签列表，便于未来分类查看 |
| `schema_version` | integer | ✅ | schema 版本号，初始为 1 |

### 哪些 TextTaskExecutionResult 字段不保存

| 原字段 | 不保存原因 |
|--------|-----------|
| `details` (全文) | 可能包含敏感信息、多行日志、traceback。只保存脱敏后的 `safe_details_excerpt`。 |
| `read_files` (tuple) | 包含文件路径，不保存完整路径列表。只保存 `read_files_count`（数量）。 |
| `error` (原始) | 原始错误码不直接保存，已反映在 `status` / `ok` / `summary` 中。 |

---

## 六、脱敏与截断规则

### 统一规则

所有写入 `task_results.jsonl` 的文本字段必须经过脱敏。

```
规则 1: summary → 脱敏后保存（summary 已由 executor 生成，但二次校验）
规则 2: safe_details_excerpt → 脱敏 + 截断（最大 500 字）
规则 3: api_key / token / password / secret / authorization / Bearer → 替换为 <redacted>
规则 4: traceback → 只取第一行（不含文件路径）
规则 5: 多行日志 → 不保存原始行，只保存统计或代表性摘要
规则 6: 路径列表 → 只保存数量，不保存完整路径
```

### 复用现有工具

`text_task_execution_service.py` 中有两个可复用的私有函数：

- **`_redact_sensitive_text()`** — 3 组正则，覆盖 `api_key=xxx`、`token=xxx`、`password=xxx`、`secret=xxx`、`authorization=xxx`、`Bearer xxx`
- **`_compact_health_text()`** — 单行化 + Traceback 截断 + 脱敏 + 长度截断

**B0 建议**：B1 实现时，这两个函数应提取到公共 util 模块（如 `src/xiaohuang/sanitize_util.py`），供 `text_task_execution_service` 和 `task_result_history_service` 共同使用。但 B0 只记录此建议，不提取代码。

### 截断参数

| 字段 | 最大长度 | 超出处理 |
|------|----------|----------|
| `summary` | 300 字 | 截断末尾 + "…" |
| `safe_details_excerpt` | 500 字 | 截断末尾 + "…" |
| `title` | 100 字 | 截断末尾 + "…" |

### 脱敏执行顺序

```
1. 先脱敏（redact regex）
2. 再紧凑化（compact — 单行、去 Traceback）
3. 再截断（按字节/字符数截断）
4. 再写入 JSONL
```

---

## 七、与现有系统的关系

### 7.1 pending task registry

| 维度 | pending task registry | task result history |
|------|----------------------|---------------------|
| **核心职责** | 管理"等待确认"的任务 | 保存"已完成"的结果 |
| **生命周期** | 短（TTL 5 分钟，确认后迁移状态） | 长（持久化到文件，不自动过期） |
| **关注点** | "能不能执行" | "结果是什么" |
| **存储** | 内存 dict | 本地 JSONL 文件 |
| **可清空** | 自动过期 + purge_expired() | 不提供清空 API（B1 至少不提供） |
| **对外接口** | register / get / claim / cancel | append / get_recent |
| **状态语义** | pending → executing → completed/blocked/failed/cancelled/expired | 只记录 completed / failed |

**两者不重叠**：registry 管理的是执行前状态，history 记录的是执行后结果。

### 7.2 runtime events

| 维度 | runtime events | task result history |
|------|---------------|---------------------|
| **核心职责** | 记录运行过程中的状态事件 | 保存用户任务完成结果 |
| **关注点** | "系统发生了什么" | "我让小黄做了什么" |
| **受众** | 开发者诊断 | 用户回看 |
| **存储** | 内存 ring buffer + `logs/runtime_events.jsonl` | `data/task_history/task_results.jsonl` |
| **可清空** | ✅ clear_recent_events() | ❌ 不提供清空 |
| **容量** | 200 条 ring buffer | 无硬限制（JSONL append-only） |
| **内容** | source/event_type/level/message | title/summary/status/result |

**关键隔离**：
- runtime events 的"清空事件"按钮**不能**清任务历史。
- 任务历史的写入失败**不能**阻止任务执行。
- 两个文件物理隔离，语义独立。

### 7.3 三者关系总览

```
用户说 "帮我做一次健康检查"
  │
  ├─→ detect_text_task_intent  → is_task=True
  ├─→ build_pending_text_task  → pending task 对象
  ├─→ registry.register()      → [pending task registry] 状态=pending
  ├─→ 用户点击"确认执行"
  ├─→ registry.claim()         → [pending task registry] 状态=executing
  ├─→ execute_confirmed_task() → 执行只读任务
  ├─→ registry.mark_completed() → [pending task registry] 状态=completed
  ├─→ record_event()           → [runtime events] 记录 capability_invoked 等
  └─→ append_task_result()     → [task result history] ★ 新增 ★ 持久化结果
```

---

## 八、存储方案评估

### 方案 A：内存 ring buffer

| 优点 | 缺点 |
|------|------|
| 实现极简，0 文件 IO | 控制面板重启后丢失 |
| 不需要路径管理 | 无法跨会话回看 |
| 不需要脱敏存储（瞬态） | 容量受限 |

### 方案 B：本地 JSONL 文件 + 内存 recent cache ★ 推荐

| 优点 | 缺点 |
|------|------|
| 控制面板重启后仍可查看 | 需要管理文件路径 |
| 实现简单，不引入数据库 | 需要处理文件不存在/损坏 |
| 便于后续导出和安全审查 | 需要设计脱敏规则 |
| append-only，写入性能好 | 无法做复杂查询（B1 不需要） |
| 一行一条 JSON，人眼可读 | 无并发锁（控制面板单进程够用） |

### 推荐

**方案 B：本地 JSONL 文件 + 内存 recent cache。**

启动时从 JSONL 加载最近 N 条到内存缓存，新结果同时写内存缓存和追加 JSONL。读取最近历史直接走内存缓存，无需每次读文件。

---

## 九、B1 最小实现范围

### B1 做什么

| 项 | 说明 |
|-----|------|
| 新建模块 | `src/xiaohuang/task_result_history_service.py` |
| 数据文件 | `data/task_history/task_results.jsonl` |
| 保存 | completed + failed 的 readonly 任务结果 |
| 读取 | `get_recent_task_results(limit=20)` |
| 脱敏 | 复用并提取 sanitize 工具函数 |
| 集成 | `ControlPanelWebApi.confirm_text_task()` 执行完成后调用 |
| 测试 | 新建 `tests/test_task_result_history_service.py` |

### B1 不做什么

| 项 | 说明 |
|-----|------|
| ❌ 不保存普通聊天消息 | 只保存 confirmed task 结果 |
| ❌ 不保存 pending/cancelled/blocked 任务 | 只保存 completed/failed |
| ❌ 不做搜索 | 未来可用 tags + grep JSONL |
| ❌ 不做分页 | 只支持最近 N 条 |
| ❌ 不做删除 | 不提供单条删除 API |
| ❌ 不做数据库 | 不上 SQLite，不上任何 DB |
| ❌ 不做前端 Tasks 页面 | B1 只做后端 API + 数据保存 |
| ❌ 不做导出 | 后续可做，但 B1 不导 |
| ❌ 不上传 | 永远不上传 |

---

## 十、模块边界

### B1 推荐模块结构

```
src/xiaohuang/task_result_history_service.py   ← 新建
tests/test_task_result_history_service.py       ← 新建
```

### 模块职责

#### `task_result_history_service.py`

```
职责：
1. 管理 task history 存储路径（data/task_history/task_results.jsonl）
2. 生成 history_id（taskhist_<uuid_hex_8>）
3. sanitize task result → safe history entry
4. append JSONL（一行一条）
5. read recent history（先查内存缓存，缓存未命中读文件）
6. 处理文件不存在/损坏/读取失败（不抛异常，返回空列表）
7. 统一脱敏和截断
```

建议函数签名：

```python
def init_task_history(project_root: Path) -> None:
    """初始化存储路径，从 JSONL 加载最近记录到内存缓存。"""
    ...

def append_task_result(
    result: TextTaskExecutionResult,
    task: dict | None = None,
) -> dict:
    """将任务执行结果脱敏后追加到历史。返回写入的 history entry。
    写入失败不抛异常，记录 runtime event warning。
    """
    ...

def get_recent_task_results(limit: int = 20) -> list[dict]:
    """返回最近的任务历史记录。从内存缓存读取。"""
    ...

def sanitize_task_result_for_history(
    result: TextTaskExecutionResult,
) -> dict:
    """将 TextTaskExecutionResult 脱敏、截断，转为安全的 history entry dict。"""
    ...
```

#### `text_task_execution_service.py`

```
职责不变：
- 执行只读任务
- 返回 TextTaskExecutionResult
- 不负责持久化历史
```

#### `control_panel_web_service.py`

```
新增职责（编排层）：
- 在 confirm_text_task() 执行完成后调用 append_task_result()
- append 失败不能影响原任务结果
- append 失败最多记录 runtime event warning
```

#### `text_task_registry_service.py`

```
职责不变：
- 管理 pending 任务注册、状态迁移
- 不负责任务结果持久化
```

#### `runtime_events/service.py`

```
职责不变：
- 记录运行事件
- 不记录任务历史
```

### 禁止的跨模块行为

| 禁止行为 | 原因 |
|----------|------|
| ❌ `control_panel_web_service.py` 直接 `open("task_results.jsonl")` | 破坏模块边界，应通过 service 层 |
| ❌ `text_task_execution_service.py` 直接写 JSONL | executor 只管执行，不管持久化 |
| ❌ 前端决定保存哪些字段 | 后端决定 schema，前端只展示 |
| ❌ 历史保存逻辑混进 `PendingTextTaskRegistry` | registry 是 pending 管理，不是历史存储 |
| ❌ task history 和 runtime events 共用 ring/file | 语义不同，生命周期不同，必须隔离 |

---

## 十一、集成点

### 后端集成点

`ControlPanelWebApi.confirm_text_task()` — 在任务执行完成并标记 registry 状态后：

```python
# 现有逻辑
if result.ok and result.status == "completed":
    self._text_task_registry.mark_completed(task_id)
elif result.status == "blocked":
    self._text_task_registry.mark_blocked(task_id, result.error)
else:
    self._text_task_registry.mark_failed(task_id, result.error)

# ★ B1 新增：将 completed/failed 结果写入历史
if result.status in ("completed", "failed"):
    try:
        append_task_result(result, task=record.task)
    except Exception:
        # append 失败不能影响原任务结果
        _record_cp_event(
            "task_history",
            "append_failed",
            f"任务历史写入失败: task_id={task_id}",
            level="warning",
        )
```

### 前端集成点（B2 或以后）

```
- Chat 右侧会话栏 → "最近任务"列表
- Tasks 页面 → 展示最近任务历史
- 任务历史卡片 → title + status + summary + time
- 点击可展开 safe_details_excerpt
```

---

## 十二、前端展示建议（B2 范围，B1 不实现）

### B2 前端最小展示

```
1. Chat 页面右侧 utility rail 增加"最近任务"折叠区
2. 每个历史条目: 时间 + title + status 标记 + summary（单行截断）
3. 点击展开 safe_details_excerpt
4. 不显示原始日志全文
5. 不显示文件路径列表
```

### 前端不做的事

```
- 不在前端拼接敏感 details
- 不在前端决定保存字段
- 不缓存历史到 localStorage（后端已持久化）
- 不提供编辑/删除功能
```

---

## 十三、安全边界

| 规则 | 说明 |
|------|------|
| 1. 保存失败不影响任务执行 | append 在 try/except 内，任何异常只记录 warning |
| 2. 不成为敏感信息泄漏点 | 所有文本字段写入前脱敏 |
| 3. 不保存原始日志 | summary/excerpt 只保留脱敏统计 |
| 4. 不保存未脱敏 details 全文 | details 原文截断为 safe_details_excerpt |
| 5. runtime events clear 不清任务历史 | 两个独立文件，独立 API |
| 6. 任务历史不是审计日志 | 不记录操作者、IP、环境变量等 |
| 7. 不自动上传 | 无网络调用 |
| 8. 不接 E:\DataBase | 纯本地 JSONL |
| 9. 不引入数据库依赖 | zero-dependency |
| 10. 不包含 API key 路径 | history 中不存任何 credentials 相关信息 |

---

## 十四、后续 B2 / B3 扩展预留

### schema_version 机制

初始 `schema_version: 1`。未来新增字段时递增版本号，读取时按版本做兼容处理。

### result_kind 分类

```text
B1:  readonly_report    (7 种只读任务)
B2:  download_result    (文件下载)
B2:  pdf_result         (PDF 解析)
B2:  crawl_result       (网页采集)
B3:  db_query_result    (数据库查询)
B3:  automation_result  (自动化任务)
```

### tags 扩展

B1 标签示例：`["health", "readonly"]`、`["error", "logs"]`、`["config"]`。

后续可用于 Tasks 页面分类筛选。

### 文件轮转（B3+）

当 `task_results.jsonl` 超过阈值（如 10000 条）时，按月份归档：
```
data/task_history/task_results.jsonl        ← 当前
data/task_history/archive/2026-05.jsonl     ← 归档
```

---

## 十五、测试建议（B1 实现时）

| 测试类别 | 内容 |
|----------|------|
| sanitize | 验证 api_key/token/password/secret/authorization/Bearer 脱敏 |
| append | 验证 JSONL 正确写入，history_id 生成 |
| read | 验证读取最近 N 条，空文件返回空列表 |
| integration | ControlPanelWebApi 确认任务后历史写入 |
| failure | 文件不可写时不抛异常，不影响任务结果 |
| truncation | 长 summary/details 正确截断 |
| edge | 不保存 pending/cancelled/blocked 任务 |

---

## 十六、Git Ignore 确认

`.gitignore` 中已有 `data/recordings/*.wav` 和 `data/recordings/wake/`，但需确认 `data/task_history/` 也被覆盖。建议在 `.gitignore` 中补充：

```
data/task_history/
```

确保实际运行产生的 task history 文件不会误提交。

---

## 十七、与现有设计文档的关系

本设计文档是 V1.5-B 系列的基石设计文档：

```
V1.5-B0  本设计文档（只设计，不实现）
V1.5-B1  后端 task_result_history_service + 集成
V1.5-B2  前端 Tasks 页面 + Chat utility rail 展示
V1.5-B3  文件轮转 + 搜索 + 筛选
```

后续 V1.5-B1 开始编码前，应先回读本文档确认模块边界和安全规则。
