# LLM Provider Configuration — V1.1.3B

> 版本：V1.1.3B
> 最后更新：2026-05-02
> 对应 commit：`ab4d058` feat: add LLM provider router

## 1. 目标

V1.1.3B 让小黄的 LLM 调用从"写死 DeepSeek"升级为"可配置的多 provider 路由"。

**当前边界：**

- 支持 4 种 provider 通过 `config.json` 切换
- 所有 provider 走 OpenAI-compatible chat completions 协议
- **不做**自动 fallback（不会 deepseek 挂了自动切 qwen）
- **不做** Settings UI（配置仍通过文本编辑 `config.json`）
- **不做**工具调用 / 长期记忆 / 多轮上下文

## 2. 配置字段

所有字段在 `config.json` 的 `llm` 段中：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | bool | `true` | 是否启用 LLM 回复 |
| `provider` | string | `"deepseek"` | 提供商标识：`deepseek` / `qwen` / `doubao` / `openai_compatible` |
| `model` | string | 见 provider 默认值 | 模型名 |
| `base_url` | string | 见 provider 默认值 | API 基础 URL（自动拼接 `/chat/completions`） |
| `api_key_env` | string | 见 provider 默认值 | 环境变量名，真实 key **不存**在 config 中 |
| `timeout_seconds` | float | `20.0` | 请求超时（秒） |
| `max_tokens` | int | `256` | 单次回复最大 token 数 |
| `temperature` | float | `0.4` | 生成温度（0.0 ~ 2.0） |

### Provider 默认值

| `provider` 值 | 默认 `base_url` | 默认 `model` | 默认 `api_key_env` |
|---------------|----------------|-------------|-------------------|
| `deepseek` | `https://api.deepseek.com` | `deepseek-v4-flash` | `DEEPSEEK_API_KEY` |
| `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-turbo` | `QWEN_API_KEY` |
| `doubao` | `https://ark.cn-beijing.volces.com/api/v3` | `doubao-lite-32k` | `DOUBAO_API_KEY` |
| `openai_compatible` | `http://127.0.0.1:8080/v1` | `default` | `OPENAI_API_KEY` |

## 3. DeepSeek 配置样例

```json
{
  "llm": {
    "enabled": true,
    "provider": "deepseek",
    "model": "deepseek-v4-flash",
    "base_url": "https://api.deepseek.com",
    "api_key_env": "DEEPSEEK_API_KEY",
    "timeout_seconds": 20,
    "max_tokens": 256,
    "temperature": 0.4
  }
}
```

```powershell
# secrets.ps1
$env:DEEPSEEK_API_KEY = "your_deepseek_key_here"
```

DeepSeek provider 会在请求体中额外添加 `"thinking": {"type": "disabled"}` 以禁用推理 token，其他 provider 不会。

## 4. Qwen（通义千问）配置样例

```json
{
  "llm": {
    "enabled": true,
    "provider": "qwen",
    "model": "qwen-turbo",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "api_key_env": "QWEN_API_KEY",
    "timeout_seconds": 20,
    "max_tokens": 256,
    "temperature": 0.4
  }
}
```

```powershell
# secrets.ps1
$env:QWEN_API_KEY = "your_qwen_key_here"
```

**注意：**

- 通义千问 API key 从[阿里云 DashScope 控制台](https://dashscope.console.aliyun.com/)获取
- `base_url` 使用 `/compatible-mode/v1` 路径兼容 OpenAI 协议
- 真实 key 放在 `secrets.ps1`，**不要放在 `config.json`**

## 5. Doubao（豆包）配置样例

```json
{
  "llm": {
    "enabled": true,
    "provider": "doubao",
    "model": "doubao-lite-32k",
    "base_url": "https://ark.cn-beijing.volces.com/api/v3",
    "api_key_env": "DOUBAO_API_KEY",
    "timeout_seconds": 20,
    "max_tokens": 256,
    "temperature": 0.4
  }
}
```

```powershell
# secrets.ps1
$env:DOUBAO_API_KEY = "your_doubao_key_here"
```

**注意：**

- 豆包 API key 从[火山引擎 Ark 控制台](https://console.volcengine.com/ark/)获取
- 需要在 Ark 中创建推理接入点（Endpoint），模型名填写接入点对应的 model ID
- 真实 key 放在 `secrets.ps1`

## 6. OpenAI-compatible 配置样例

```json
{
  "llm": {
    "enabled": true,
    "provider": "openai_compatible",
    "model": "llama-3-8b-instruct",
    "base_url": "http://127.0.0.1:8080/v1",
    "api_key_env": "LOCAL_LLM_API_KEY",
    "timeout_seconds": 30,
    "max_tokens": 256,
    "temperature": 0.4
  }
}
```

```powershell
# secrets.ps1
$env:LOCAL_LLM_API_KEY = "your_local_key_here"
```

**注意：**

- `base_url` **必须显式写清**，不会从默认值推导
- `model` 按目标服务实际模型名填写（如 `llama-3-8b-instruct`、`gpt-4o-mini`、`mistral-7b`）
- `api_key_env` 可自定义为任意环境变量名，例如 `LOCAL_LLM_API_KEY`、`OPENAI_API_KEY`、`OLLAMA_API_KEY`
- 适用于：本地 Ollama、vLLM、LM Studio、OpenAI 兼容代理、自定义 API 网关

## 7. secrets.ps1 示例

```powershell
# ============================================================
# XiaoHuang LLM API Keys
# 位置：$env:USERPROFILE\.xiaohuang\secrets.ps1
# 此文件不会被提交到 Git（已在 .gitignore 中）
# ============================================================

# DeepSeek
$env:DEEPSEEK_API_KEY = "your_deepseek_key_here"

# Qwen（通义千问）
$env:QWEN_API_KEY = "your_qwen_key_here"

# Doubao（豆包）
$env:DOUBAO_API_KEY = "your_doubao_key_here"

# OpenAI-compatible（本地或自定义）
$env:OPENAI_API_KEY = "your_openai_key_here"
$env:LOCAL_LLM_API_KEY = "your_local_key_here"
```

**安全规则：**

- 所有 key 值只能写占位符（如 `your_deepseek_key_here`），绝不写真实 key
- `config.json` 只存 `api_key_env`（环境变量名），不存 key 值
- 日志不打印 `Authorization` header、API key、完整 system prompt
- API key 绝不会出现在 request payload 中
- `_redact_url()` 自动脱敏 URL 中的 key 参数

## 8. 没有 key 时的预期行为

当 `api_key_env` 对应的环境变量未设置或为空时：

| 行为 | 说明 |
|------|------|
| **不崩溃** | 不会因为缺少 key 而抛异常 |
| **`is_configured=False`** | `load_llm_provider_config` 返回的 `LlmReplyConfig.is_configured` 为 `False` |
| **fallback 到规则回复** | `generate_llm_reply_result` 检测到 `is_configured=False` 后返回 `source="rule_fallback_no_key"` |
| **不打印完整 key** | 错误日志只记录 `api_key_env` 变量名，不打印 key 值 |

### Debug 模式下的输出示例

```
LLM API key 未配置（DEEPSEEK_API_KEY），已使用本地规则回复
```

### 有 key 时的 debug 输出

```
LLM enabled: provider=deepseek model=deepseek-v4-flash max_tokens=256 timeout=20.0s
```

注意：debug 输出包含 `provider` / `model` / `max_tokens` / `timeout`，**不包含 API key**。

## 9. 真实验证命令

```powershell
# 停止现有进程
.\scripts\stop_xiaohuang.ps1 -StopSttServer

# 使用测试配置启动（provider=deepseek）
.\scripts\start_xiaohuang.ps1 -ConfigPath "$env:USERPROFILE\.xiaohuang\config_test.json"

# 切换 provider 测试（编辑 config_test.json 后重新启动）
notepad "$env:USERPROFILE\.xiaohuang\config_test.json"
.\scripts\stop_xiaohuang.ps1 -StopSttServer
.\scripts\start_xiaohuang.ps1 -ConfigPath "$env:USERPROFILE\.xiaohuang\config_test.json"
```

### 测试流程

1. 启动后确认悬浮窗出现（resident_hidden=true 时唤醒后出现）
2. 说唤醒词 → 悬浮窗弹出
3. 说"你是谁？" → 观察回复
4. 说"好了" → 退出会话
5. 检查日志确认 `source=llm` 且无错误

## 10. 日志检查命令

```powershell
Get-Content .\logs\voice_overlay.err.log -Tail 500 | Select-String "LLM enabled|provider=|Overlay command|Overlay reply|Session ended|Traceback|ERROR|HTTPError|TypeError|UnboundLocalError"
```

### 正常日志示例（DeepSeek 真实验证通过）

```
Overlay command: 你是谁？
Overlay reply: 我是贾维斯，你的桌面语音助手。 (source=llm)
```

如果出现以下行则说明有问题：

```
Traceback
ERROR
HTTPError
TypeError
UnboundLocalError
Authentication
```

## 11. 当前已验证状态

| Provider | 单元测试 | 真实 API 验证 | 备注 |
|----------|---------|-------------|------|
| `deepseek` | 11 tests PASS | ✅ 已通过（source=llm） | 用户真实验证：问"你是谁" → "我是贾维斯" |
| `qwen` | 11 tests PASS | ⏳ 待用户配置真实 key | 需阿里云 DashScope API key |
| `doubao` | 11 tests PASS | ⏳ 待用户配置真实 key | 需火山引擎 Ark API key + 推理接入点 |
| `openai_compatible` | 11 tests PASS | ⏳ 待用户配置对应服务 | 需本地或远程 OpenAI-compatible 服务 |

### 单元测试覆盖（`V113BLlmProviderRouterTests`）

- provider=deepseek/qwen/doubao/openai_compatible 配置加载
- api_key_env 缺失时 graceful fallback（不崩溃）
- temperature/max_tokens/timeout 从 config 传入请求
- DeepSeek 请求包含 `thinking: disabled`，其他 provider 不包含
- `build_deepseek_request` 向后兼容
- persona 流入 system prompt
- API key 不进入 request payload
- CLI 未传参时 config 值不被覆盖

## 架构参考

```
config.json llm 段
    ↓
LlmConfig (app_config_service)
    ↓
load_llm_provider_config(app_llm_config)
    ↓ 读取 os.environ[api_key_env]
LlmReplyConfig (api_key, base_url, model, timeout, max_tokens, temperature, provider)
    ↓
build_openai_compatible_chat_request(provider=...)
    ↓ 仅 deepseek 加 thinking:disabled
POST /chat/completions  →  回复文本
```

## 关联文档

- [configuration.md](configuration.md) — 全部配置字段参考
- [V1.1.3A_CONFIG_AUDIT.md](V1.1.3A_CONFIG_AUDIT.md) — 中控层收口审计
