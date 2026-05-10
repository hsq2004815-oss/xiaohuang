# V1.5-C0 自然语言动作型任务安全设计

## 版本

| 项目 | 值 |
|------|-----|
| 文档版本 | C0（仅设计，无代码实现） |
| 日期 | 2026-05-10 |
| 状态 | 设计完成，待 C1 实现 |

---

## 1. 目标

为小黄下一阶段"动作型任务（action task）"建立统一的安全设计。核心升级：

**将"text task"概念升级为"natural language task"（自然语言任务）**，统一支持文本输入和语音输入两种来源。

---

## 2. 背景

### 当前已完成

```
V1.4-D 系列   文本任务确认与只读执行
V1.5-A 系列   健康报告自诊断
V1.5-B 系列   任务历史与结果沉淀
```

当前小黄已有：
- pending task registry（任务确认注册表）
- confirmed text task execution（确认后执行）
- 7 种 readonly task types（只读白名单）
- task result history（任务历史持久化）
- Tasks 页面（历史回看）
- runtime events（运行事件）
- 语音唤醒 / ASR 转写基础能力

### 需要解决的新问题

后续要支持用户通过语音或文本下达"动作型任务"，例如"打开日志目录"。这会带来比只读任务更高的安全风险，必须提前设计安全边界。

---

## 3. text task / voice task / natural language task 的关系

### 概念定义

| 概念 | 定义 |
|------|------|
| **text task** | 用户在输入框中打字形成的任务候选 |
| **voice task** | 用户通过语音说话，ASR 转写成文本后形成的任务候选 |
| **natural language task** | 统一抽象层。无论来源是文本还是语音，只要被识别为任务，都进入同一个 pending / confirmation / execution / history 流程 |

### 核心原则

```
语音和文本只是输入通道不同。
任务识别、风险分类、用户确认、执行、历史记录应该尽量统一。
```

### 当前代码命名

现有 `text_task_*` 命名的文件在 V1.5-C 阶段短期保留，不做重命名：
- `text_task_intent_service.py`
- `text_task_execution_service.py`
- `text_task_registry_service.py`
- `text_task_models.py` / `text_task_execution_models.py` / `text_task_registry_models.py`

未来可逐步抽象为 `natural_language_task`，但必须小步迁移，不在 C 阶段批量重命名。

### 统一流程

```
文本输入 ─┐
          ├→ 任务识别 → pending task → 用户确认 → 执行 → 任务历史
语音输入 ─┘
  (ASR转写)
```

---

## 4. 语音下达任务的安全规则

### 基础原则

```
1. 唤醒词只代表开始监听，不代表授权执行。
2. ASR 转写结果只是一段候选文本，不是可信命令。
3. 语音 action task 必须进入 pending registry。
4. action task 不允许语音直接执行。
5. 确认卡片必须显示 ASR 原始转写文本。
6. 确认卡片必须显示任务解释后的标题、目标和影响范围。
7. 如果 ASR 置信度不足，应要求用户重新确认或改为文本确认。
8. 用户说"确认"只能确认当前有效 pending task，不能确认过期任务。
9. 用户说"确认"前必须已有明确可见的确认卡片。
10. 误唤醒时不能产生可执行 action task。
11. 多个 pending task 同时存在时，语音确认必须绑定明确 task_id。
12. 任何 blocked / dangerous action 即使用户说确认，也不能执行。
13. 语音取消应只取消当前 pending task，不影响历史记录。
14. 语音输入不应扩大权限。
15. 语音任务执行结果必须进入 task history。
```

### 安全层级

```
唤醒词 → 开始监听（不是授权）
  ↓
ASR 转写 → 候选文本（不是命令）
  ↓
任务识别 → 判断意图
  ↓
pending registry → 等待确认
  ↓
用户确认 → 必须可见卡片 + 明确操作
  ↓
执行 → 白名单 + 权限检查
  ↓
task history → 脱敏摘要
```

---

## 5. ASR 转写与置信度设计

### 建议 pending task 扩展字段

```json
{
  "source": "voice",
  "input_text": "小黄，打开日志目录",
  "transcript": "小黄，打开日志目录",
  "asr_confidence": 0.86,
  "asr_confidence_level": "medium",
  "requires_reconfirm": false
}
```

### 设计决策

| 规则 | 说明 |
|------|------|
| ASR result 应保存为候选输入文本 | transcript 字段 |
| confirmation card 应展示 `source = "voice"` | 用户知道这是语音识别结果 |
| confirmation card 应展示 transcript | 用户可核对识别是否正确 |
| 如果 ASR 支持 confidence | 使用 `asr_confidence` (float) + `asr_confidence_level` (high/medium/low) |
| 低置信度语音任务不能直接确认 | `requires_reconfirm = true` |
| 低置信度 action task 应要求二次确认 | 或改为文本确认 |
| transcript 不应长期保存原始音频 | task history 不存音频 |
| task history 可保存脱敏 transcript excerpt | 不保存原始音频文件 |

### 置信度阈值建议（后续实现参考）

```
high:   ≥ 0.80 → 正常确认流程
medium: 0.50-0.79 → 确认卡片额外提醒，可要求二次确认
low:    < 0.50 → 要求用户重新说话或改为文本确认
```

---

## 6. 误唤醒与非任务语音处理

### 非任务表达

以下类型的用户发言不应生成可执行任务：

```
"算了"       → 放弃意图
"不是"       → 否定
"等一下"     → 延迟
"你在吗"     → 问候/测试
"打开那个"   → 指代不明
"删掉它"     → 指代不明 + 危险意图
```

### 处理规则

| 场景 | 处理方式 |
|------|----------|
| 唤醒后说闲聊内容 | 不应强行生成 task |
| 低置信度短句 | 不应生成 action task |
| 模糊命令 | 反问或生成非可执行候选 |
| 带危险意图的模糊语音 | 默认 blocked |
| 误唤醒 | 记录 runtime event (warning)，不进入 task history |

---

## 7. readonly task 与 action task 的区别

| 维度 | readonly task | action task |
|------|--------------|-------------|
| **定义** | 只读取信息，不改变外部状态 | 触发确定动作，可能改变状态 |
| **示例** | 健康检查、日志错误摘要、配置摘要 | 打开日志目录、清空运行事件 |
| **风险** | low | low 到 high，取决于动作 |
| **确认** | 需要 | 必须，条件更严格 |
| **语音执行** | 可以（仍需确认） | 可以（必须确认），不得绕过 |
| **失败影响** | 仅影响返回内容 | 可能影响本地状态 |

---

## 8. 动作分类

### 四类动作

#### readonly（只读）

```
只读，不改变外部状态。
- 健康检查
- 最近错误摘要
- 配置摘要
- 最近任务历史摘要
- 运行事件摘要
```

#### safe_action（安全动作）

```
低风险动作，只打开或展示，不删除、不覆盖、不写入。
- 打开日志目录
- 打开配置文件所在目录
- 打开项目目录
- 打开任务历史数据目录
- 打开控制面板页面

注意：safe_action 也必须用户确认。语音下达时不能自动执行。
```

#### controlled_action（受控动作）

```
中风险动作，会改变小黄内部运行状态或清理可恢复状态。
- 清空 runtime events
- 重启语音服务
- 重启控制面板 bridge
- 切换非危险配置开关

要求：必须确认，确认卡片需明确显示影响范围。
语音触发时比文本更保守，可要求二次确认。
```

#### dangerous_action（危险动作）

```
高风险动作，默认禁止或未来必须强确认。
- 删除文件 / 目录
- 覆盖文件
- 批量移动 / 重命名文件
- 运行任意 shell 命令
- 修改系统环境变量 / PATH / 注册表
- 安装 / 卸载软件
- 发送消息 / 邮件
- 浏览器自动提交表单
- 自动付款 / 下单
- 上传隐私文件

要求：V1.5-C 阶段默认不实现 dangerous_action。
语音触发 dangerous_action 必须 blocked。
```

---

## 9. 风险等级

| 等级 | 说明 | 默认对应 |
|------|------|----------|
| **low** | 只读或低风险，确认后执行 | readonly, safe_action |
| **medium** | 中风险，需强确认 + 影响说明 | controlled_action, 低置信度语音 |
| **high** | 高风险，需特别授权 | dangerous_action（如开放需强确认） |
| **blocked** | 当前版本禁止执行 | dangerous_action 默认值, 模糊危险意图 |

### 语音任务的额外风险级别

```
低置信度语音 action → 至少 medium 或 requires_reconfirm=true
模糊语音 dangerous intent → blocked
语音 controlled_action → 至少 medium（比文本更保守）
```

---

## 10. 统一确认流程

### 确认卡片字段设计

```json
{
  "task_id": "nl-task-...",
  "task_type": "safe_open_logs_dir",
  "category": "safe_action",
  "risk_level": "low",
  "source": "voice",
  "input_text": "小黄，打开日志目录",
  "transcript": "小黄，打开日志目录",
  "asr_confidence": 0.86,
  "asr_confidence_level": "medium",
  "title": "打开日志目录",
  "summary": "将在文件管理器中打开小黄日志目录。",
  "target_label": "日志目录",
  "target_display": "E:\\Projects\\xiaohuang\\logs",
  "impact": "只打开目录，不修改文件。",
  "allowed": true,
  "requires_confirmation": true,
  "requires_reconfirm": false,
  "blocked_reason": ""
}
```

### 确认要求

```
1. action task 不允许自动执行
2. 语音 action task 不允许直接执行
3. 必须走 pending task registry
4. 必须显示 source（voice/text）
5. 如果 source=voice，必须显示 ASR transcript
6. 必须显示 action category
7. 必须显示 risk level
8. 必须显示 target
9. 必须显示 impact（影响范围说明）
10. dangerous_action 默认 blocked
11. blocked 任务不能给确认按钮
12. 低置信度语音任务需要重新确认或文本确认
```

### 语音任务确认卡片额外显示

```
"这是根据语音识别结果生成的任务，请确认识别内容和动作目标。"
```

### dangerous_action 卡片应显示

```
"此类操作当前不支持"
```

而不是给确认按钮。

---

## 11. 语音确认词规则

### 确认词管理

```
1. "确认""执行""可以""继续"等语音确认词不能作为通用授权
2. 只有当前存在一个明确 active pending task，且确认卡片可见时，确认词才可能生效
3. 确认词必须绑定 task_id
4. 确认词不能确认 expired/cancelled/blocked task
5. 如果多个 pending task 存在，必须要求用户选择或重新说明
6. 高风险/blocked 任务不能通过语音确认绕过限制
7. 语音取消词只取消当前 pending task（"取消""算了""别执行"）
```

### 确认词安全链

```
用户说"确认"
  → 检查是否存在 active pending task
  → 检查是否有且只有一个（多个时反问）
  → 检查 task 未过期
  → 检查 task 未被 blocked
  → 检查 action category 允许语音确认
  → 执行
```

---

## 12. 禁止自动化清单

以下操作在 V1.5-C 阶段默认禁止，无论文本还是语音触发：

```
1.  删除文件/目录
2.  覆盖文件
3.  批量移动/重命名
4.  运行任意 shell 命令
5.  执行用户自然语言拼出来的命令
6.  修改系统 PATH/环境变量/注册表
7.  安装/卸载软件
8.  改动系统服务
9.  上传文件
10. 发送消息/邮件
11. 浏览器自动提交表单
12. 自动支付/下单
13. 访问/读取密码、token、cookie、浏览器凭据
14. 读取大范围个人目录（如整个 C:\Users）
15. 对 E:\DataBase 执行写入/删除
16. 通过语音直接执行 destructive action
17. 使用"确认"绕过 blocked action
```

---

## 13. C1 最小实现范围

### V1.5-C1 Safe Local Open Actions

C1 只允许 voice-or-text 触发以下 safe local open actions：

| 动作 | 目标路径计算 |
|------|-------------|
| 打开日志目录 | `project_root / "logs"` |
| 打开配置文件所在目录 | `config_path.parent` |
| 打开项目目录 | `project_root` |
| 打开任务历史数据目录 | `project_root / "data" / "task_history"` |

### C1 允许

```
1. 使用白名单路径（后端基于 project_root/config_path 计算）
2. 前端只显示 target_display，不决定真实目标路径
3. 用户确认后执行（文本和语音均需确认）
4. 语音来源也必须确认
5. 执行结果写入 task history
6. 失败写入 runtime event warning
```

### C1 禁止

```
1.  删除 / 写入 / 覆盖 / 移动 / 重命名
2.  运行任意命令
3.  打开任意用户输入路径
4.  打开网络 URL
5.  打开 E:\DataBase 写入路径
6.  语音直接跳过确认执行
7.  保存原始音频
```

---

## 14. 与 pending registry 的关系

```
1. 所有 action task 先进入 pending registry
2. voice/text source 都进入同一个 registry 流程
3. 用户确认后才能 claim
4. blocked action 不能 claim
5. expired/cancelled 不执行
6. registry 仍只保存短期任务（TTL 5 分钟），不保存长期结果
7. pending task 应包含 source/input_text/transcript/asr_confidence 等可选字段
8. voice confirmation 必须绑定当前有效 task_id
```

---

## 15. 与 task result history 的关系

```
1. action task 执行结果也应进入 task result history
2. history 只保存安全摘要
3. 不保存完整路径列表
4. 不保存敏感配置内容
5. 不保存异常 traceback 全文
6. 不保存原始音频
7. 可保存脱敏后的 transcript excerpt
8. result_kind 可扩展为 "action_result"（当前为 "readonly_report"）
9. tags 可包含 ["action", "open", "local", "voice"] 或 ["action", "open", "local", "text"]
```

---

## 16. 与 runtime events 的关系

```
1. runtime events 记录过程事件
2. task history 记录用户可回看的结果
3. action start / success / failed 可以记 runtime event
4. ASR low confidence / miswake / blocked action 可记 warning event
5. runtime events clear 不能清 task history
6. action task 被 blocked 也可以记 warning event
```

---

## 17. 失败处理

```
1. 执行失败不能导致控制面板崩溃
2. 失败结果要显示给用户（result card）
3. 失败结果写入 task history（status=failed, 脱敏摘要）
4. 失败只保存脱敏摘要（不保存完整 traceback）
5. 失败可以写 runtime event warning
6. 不暴露原始 traceback
7. 语音任务失败不保存音频
8. 如果失败原因来自 ASR 不明确，提示用户重新下达或改用文本
```

---

## 18. UI 确认卡片设计（Bounded Decision，不实现）

### 通用确认卡片字段

```
- 任务标题 (title)
- 输入来源 (source: 语音 / 文本)
- 原始输入文本 (input_text)
- ASR 转写文本 (transcript, 仅 source=voice 时显示)
- 动作类型 (category: readonly / safe_action / controlled_action / dangerous_action)
- 风险等级 (risk_level)
- 目标 (target_label)
- 目标路径 (target_display, 只读展示)
- 影响范围 (impact)
- 允许 / 禁止原因 (allowed + blocked_reason)
- 确认按钮（仅 allowed=true 时显示）
- 取消按钮
```

### voice task 额外提示

```
这是根据语音识别结果生成的任务，请确认识别内容和动作目标。
```

### dangerous_action 展示

```
此类操作当前不支持
→ 无确认按钮
```

---

## 19. 后续路线

```
C0: 本设计文档 — voice-or-text natural language task 安全设计
C1: Safe Local Open Actions — 语音或文本触发白名单路径打开
C2: Controlled Local Actions — 清空 runtime events / 重启轻量模块
C3: Download Task Safety Design + Implementation
C4: PDF Parse Task
C5: Database Query Task — 只读接入外部数据源
C6: Browser Automation Safety Design — 独立安全设计
```

### 路线原则

```
- 数据库查询只能先只读
- 浏览器自动化必须单独安全设计，不混进 C1
- 语音确认能力必须谨慎推进，不能让"确认"成为万能授权
- 每一步都必须有独立的设计文档和安全评审
```

---

## 20. Bounded Decisions / 当前决策

本节记录 C0 阶段做的有限决策，防止后续偏离。

```
1.  V1.5-C 阶段默认不支持 dangerous_action
2.  C1 只做白名单 safe local open actions（4 个）
3.  任何动作型任务都必须用户确认
4.  语音只是输入通道，不是授权
5.  唤醒词不是授权
6.  ASR 转写不是可信命令
7.  前端不能决定真实目标路径
8.  后端必须使用白名单路径（基于 project_root/config_path 计算）
9.  现有 text_task_* 命名短期保留，不在 C0 重命名
10. action task 执行结果必须进入 task history（脱敏）
11. C1 不保存原始音频
12. 不接 E:\DataBase 写入路径
```
