# V1.0 Backend Foundation — Step 1B: Source Audit

> 基于 `E:\Projects\xiaohuang` 2026-05-01 实际源码。每条声明均标注"源码确认"/"规则建议"/"未验证假设"。

---

## 一、源码文件清单（实际读取）

| 文件 | 行数 | 类型 |
|------|------|------|
| `scripts/voice_overlay.py` | 493 | 入口脚本 |
| `scripts/stt_server.py` | 136 | 入口脚本 |
| `scripts/wake_loop.py` | 164 | 入口脚本 |
| `src/xiaohuang/wake_loop_service.py` | 132 | 服务 |
| `src/xiaohuang/wake_word_service.py` | 94 | 服务 |
| `src/xiaohuang/stt_client_service.py` | 64 | 客户端 |
| `src/xiaohuang/stt_server_service.py` | 58 | 服务端 |
| `src/xiaohuang/stt_service.py` | 183 | STT 引擎包装 |
| `src/xiaohuang/llm_reply_service.py` | 267 | LLM 客户端 |
| `src/xiaohuang/reply_service.py` | 60 | 规则回复 |
| `src/xiaohuang/tts_service.py` | 56 | TTS 合成 |
| `src/xiaohuang/audio_playback_service.py` | 21 | 音频播放 |
| `src/xiaohuang/audio_capture_service.py` | 152 | 音频采集 |
| `src/xiaohuang/vad_recording_service.py` | 232 | VAD 录音 |
| `src/xiaohuang/vad_service.py` | 17 | VAD 占位 |
| `src/xiaohuang/overlay_state_service.py` | 59 | 浮窗状态 |
| `src/xiaohuang/overlay_runtime_service.py` | 8 | 冷却时间 |
| `src/xiaohuang/config_service.py` | 104 | 配置加载 |
| `src/xiaohuang/logging_service.py` | 29 | 日志配置 |
| `src/xiaohuang/listen_once_service.py` | 82 | 单次录音 |
| `config/xiaohuang.yaml` | 20 | 配置文件 |
| `requirements.txt` | 12 | 依赖 |
| `tests/test_core_services.py` | ~1100 | 测试（111 用例） |

---

## 二、voice_overlay.py 真实职责

### 源码确认

**VoiceOverlayApp 类 (line 65–239):**
- Tkinter 窗口创建、无边框置顶窗口、拖拽移动（`_start_move`/`_move`）
- 音波动画 Canvas（`_animate`，每 90ms 自调度）
- 状态文本更新（`set_state`、`show_status`）
- 线程安全的 UI 更新（`thread_safe_set_state`、`thread_safe_show_status`）
- after ID 追踪 + close 取消 + TclError 保护

**`_run_overlay_loop` 函数 (line 340–442):**
- 调用 `run_wake_loop_once` 编排唤醒→命令循环
- 实现 `_overlay_stt` 包装器：调用次数 `_stt_call_count["n"]` 区分 wake check (n==1) vs command (n>=2)
- wake check STT 500 → `return {"text": ""}`（跳过本轮）
- command STT 500 → 重新 raise，外层 catch 处理
- LLM/规则回复选择逻辑（`enable_llm` + `llm_config.is_configured`）
- TTS 合成+播放（edge-tts → mp3 → `os.startfile`）
- Post-response cooldown（默认 6s/3.5s）
- 异常处理三层：`SttServer*` → warning 跳过；`Exception` → `logger.exception` + error 状态

**`main()` 函数 (line 242–337):**
- argparse 参数解析
- STT server health check（启动前验证）
- WakeLoopOptions 构建
- LLM 配置加载（`load_deepseek_config`）
- 调试打印：STT server ready / LLM enabled / TTS enabled / no-key warning
- daemon thread 启动 `_run_overlay_loop`
- Tk mainloop → 关闭后 `stop_event.set()` + `worker.join(1.0)`

### 职责分类

| 职责 | 是否应保留在 voice_overlay.py | 理由 |
|------|------------------------------|------|
| Tkinter 窗口/动画/拖拽 | ✅ 保留 | 这是 UI 层，没有其他地方放 |
| UI 线程安全更新 | ✅ 保留 | 与 Tkinter 紧耦合 |
| argparse 参数解析 | ✅ 保留 | CLI 入口约定 |
| WakeLoopOptions 构建 | ⚠️ 可迁出 | 纯数据组装，不依赖 Tkinter |
| `_run_overlay_loop` wake 编排 | ⚠️ 可迁出 | 业务逻辑，不依赖 Tkinter（除 `app.thread_safe_set_state`） |
| LLM/规则回复选择 | ⚠️ 可迁出 | 纯数据流，可独立测试 |
| TTS 合成+播放 | ⚠️ 可迁出 | 底层已有 `tts_service`，编排逻辑可移出 |
| `_overlay_stt` 包装器 | ❌ 应在 V1.0.3 替换 | 调用计数 hack，应用显式 phase 替换 |
| Post-response cooldown | ⚠️ 可迁出 | 简单 wait，非核心 |
| 异常处理三层 | ⚠️ 可迁出 | 应与 phase 绑定而非在 while 循环里 |

### 绝对禁区（V1.0.1 不改）

- `VoiceOverlayApp` 类任何方法（Tkinter 回调保护是 V0.9.1 刚稳定下来的）
- `_run_overlay_loop` 整体结构（V1.0.3 才动）
- `_overlay_stt` 包装器（V1.0.3 才替换）
- TTS 合成/播放逻辑（用户明确禁止）

---

## 三、STT Server/Client 真实接口

### 源码确认

**STT Server (`scripts/stt_server.py`):**

Endpoints:
- `GET /health` → `200 {"ok": true, "status": "ready", "server_model_init_seconds": 24.75}`
- `POST /transcribe` → `200 {"ok": true, "text": "...", "server_model_init_seconds": ..., "transcribe_seconds": ..., "total_seconds": ...}`
- 其他路径 → `404 {"ok": false, "error": "Not found."}`

错误响应格式（源码确认）:
- 缺 wav_path → `400 {"ok": false, "error": "Missing wav_path."}`
- PathGuardError → `400 {"ok": false, "error": "<guard message>"}`
- 转写异常 → `500 {"ok": false, "error": "<str(exc)>"}`
- **未使用 `request_id`、未使用 `code` 字段**
- **500 响应直接 `str(exc)` 裸错误信息，有泄漏 traceback 片段的可能**

请求格式: `POST /transcribe` body: `{"wav_path": "data/recordings/test.wav"}`

**STT Server Service (`src/xiaohuang/stt_server_service.py`):**

存在。提供：
- `build_success_response(text, server_model_init_seconds, transcribe_seconds, total_seconds)` → `{"ok": true, "text": ..., ...}`
- `build_error_response(message)` → `{"ok": false, "error": message}`
- `resolve_recording_wav_path(wav_path, project_root)` → 路径安全校验
- `PathGuardError` 异常类

**STT Client Service (`src/xiaohuang/stt_client_service.py`):**

存在。提供：
- `check_server_health(server_url, timeout_seconds=5.0)` → `dict`
- `request_transcription(wav_path, server_url, timeout_seconds=120.0)` → `dict`
- `SttServerUnavailable(RuntimeError)` — 连接不上
- `SttServerError(RuntimeError)` — 服务端返回错误
- `build_transcribe_payload(wav_path)` → `{"wav_path": "..."}`
- `build_health_url(server_url)` → `"http://...:8766/health"`

**错误分类（现状）:**
- `SttServerUnavailable`: DNS/connect refused/timeout/OSError
- `SttServerError`: HTTP 非200、JSON 无效、ok=false
- **没有细分 4xx vs 5xx vs invalid JSON vs ok=false**

---

## 四、Wake Check / Command 真实区分方式

### 源码确认

```python
# scripts/voice_overlay.py line 353–366
_stt_call_count = {"n": 0}

def _overlay_stt(path, server_url):
    _stt_call_count["n"] += 1
    try:
        return request_transcription(path, server_url)
    except (SttServerUnavailable, SttServerError) as exc:
        if _stt_call_count["n"] == 1:     # <-- 调用次数判断
            # wake check — skip this window
            ...
            return {"text": ""}
        raise                              # command — 向上传播
```

- **是，使用调用次数判断**（`_stt_call_count["n"] == 1`）
- 变量 `_stt_call_count` 是 dict 包装的 int（闭包内可变）
- 每轮 `while not stop_event.is_set()` 开始时重置 `_stt_call_count["n"] = 0`
- `run_wake_loop_once` 内部依次调用：wake check transcription → command transcription
- wake check 可能循环多次（直到检测到唤醒词），但 STT 每次调用 count 递增

**后续最小改动点：**
- `run_wake_loop_once` 的 `request_transcription_func` 参数可改为接受 `(path, server_url, mode)` 其中 `mode` 是 `"wake"` 或 `"command"`
- 或把 `run_wake_loop_once` 拆成两个独立函数调用：`run_wake_check()` + `run_command_recording()`

---

## 五、DeepSeek / LLM 真实链路

### 源码确认

**模型与默认值 (`llm_reply_service.py`):**
- 默认模型: `"deepseek-v4-flash"` (line 13)
- 默认 base URL: `"https://api.deepseek.com"` (line 12)
- 默认 timeout: 15s（`load_deepseek_config` 参数，voice_overlay.py 传入）
- 默认 max_tokens: **256**（line 34, 69）
- thinking: `{"type": "disabled"}`（line 85）— **源码确认**

**请求构建 (`build_deepseek_request` line 69–86):**
```python
{
    "model": "...",
    "messages": [
        {"role": "system", "content": "你是 Windows 桌面语音助手小黄。只做单句自然回复，30 个汉字以内。..."},
        {"role": "user", "content": "<user_text>"}
    ],
    "temperature": 0.4,
    "max_tokens": 256,
    "stream": False,
    "thinking": {"type": "disabled"}
}
```

**回复清洗 (`_shorten_reply` line 184–188):**
- 去多余空白：`" ".join(str(text or "").split()).strip()`
- **30 字硬截断**：`len(cleaned) > 30` → 截断到 30 字 + `"。"` — **源码确认**
- 截断时去掉末尾标点再加句号

**Fallback 策略 (`generate_llm_reply_result` line 106–154):**
1. `_looks_like_tool_request(user_text)` → `source="tool_unavailable"` ← **先于任何 LLM 调用**
2. `!is_configured` → `source="rule_fallback_no_key"`
3. Exception → `source="rule_fallback_error"`
4. Response 有 `error` 字段 → `source="rule_fallback_error"`
5. `_shorten_reply` 后非空 + `_looks_like_execution_claim` → `source="tool_unavailable"`
6. `_shorten_reply` 后非空 + no execution claim → `source="llm"`
7. empty + `finish_reason=="length"` → `source="rule_fallback_length"`
8. empty + other → `source="rule_fallback_empty"`

**工具请求拦截 (`_looks_like_tool_request` line 191–209):**
- 29 个关键词匹配
- 当前属于 LLM reply service 内部逻辑
- **不在独立 task_router 中**
- **只在 LLM 路径生效**：如果 `--enable-llm` 未开启，走规则回复不经过此拦截

**安全调试摘要 (`build_deepseek_response_debug_summary` line 216–244):**
- 只输出：has_error / error_type / error_message（截断）/ choices_count / finish_reason / has_message / content_length / model / has_usage
- **不输出** API key / Authorization / 完整 prompt / 完整响应 — **源码确认**

### 禁区（V1.0.1 不改）

- `build_deepseek_request` 参数签名
- `_shorten_reply` 30 字限制
- `_looks_like_tool_request` 关键词列表
- `_looks_like_execution_claim` 关键词列表
- `generate_llm_reply_result` fallback 决策顺序
- thinking disabled 设置

---

## 六、TTS 真实链路

### 源码确认

**`tts_service.py`:**
- `clean_tts_text(text)` → 去多余空白，空文本 → `"我在。"`
- `synthesize_tts_to_mp3(text, output_dir, voice="zh-CN-XiaoxiaoNeural")` → 调用 edge-tts
- `build_tts_output_path(output_dir, timestamp)` → `data/tts/tts_YYYYMMDD_HHMMSS.mp3`
- 使用 `asyncio.run` 同步化 `edge_tts.Communicate.save()`

**`audio_playback_service.py`:**
- `play_audio_file(audio_path)` → `os.startfile(str(path))` — Windows 默认程序打开 mp3
- 失败 → warning print，不抛异常，返回 `False`

**Overlay 中 TTS 调用 (`voice_overlay.py` line 408–419):**
- 条件：`enable_tts and not stop_event.is_set()`
- 状态：先 `STATE_SPEAKING`，然后合成+播放
- 异常处理：
  - `MissingTtsDependencyError` → warning + STATE_ERROR
  - `Exception` → warning + STATE_ERROR
- TTS 失败不阻塞，文字已显示在 STATE_RESULT 中

### 禁区（V1.0.1 不改）

- `synthesize_tts_to_mp3` 签名和行为
- `play_audio_file` 使用 `os.startfile`
- TTS 失败 fallback 已正确：文字显示不受影响

---

## 七、测试现状

### 源码确认

- 测试文件：`tests/test_core_services.py`（~1100 行）
- **实际运行确认：111 tests，全部通过**（2026-05-01 实测）
- 测试框架：`unittest`（标准库）
- 运行命令：`"F:\for_xiaohuang\conda310\python.exe" -m unittest discover -s tests`
- compileall 命令：`"F:\for_xiaohuang\conda310\python.exe" -m compileall -q src scripts tests`

**测试覆盖范围：**
- `ConfigServiceTests` — 1 test
- `AudioCaptureServiceTests` — 6 tests
- `VadServiceTests` — 1 test
- `VadRecordingServiceTests` — 6 tests
- `SttServiceTests` — 4 tests
- `ListenOnceServiceTests` — 7 tests
- `SttServerServiceTests` — 6 tests
- `SttClientServiceTests` — 2 tests
- `ReplyServiceTests` — 6 tests
- `LlmReplyServiceTests` — 30 tests
- `TtsServiceTests` — 2 tests
- `WakeWordServiceTests` — 12 tests
- `OverlayStateServiceTests` — 7 tests
- `OverlayRuntimeServiceTests` — 2 tests
- `WakeLoopServiceTests` — 3 tests
- `VoiceOverlayGuardTests` — 5 tests（Tkinter 需要 display）
- `SourceNoteTests` — 7 tests

---

## 八、上一轮文档需要修正的内容

| 上一轮声称 | 问题 | 源码事实 | 修正 |
|-----------|------|---------|------|
| `max_tokens` 默认 96 | 过时 | **256**（三轮已改为 256） | ✅ 更新 |
| STT server /health 返回 `error` 字段 | 错误 | 只返回 `ok`/`status`/`server_model_init_seconds`，**没有 `error` 字段** | ✅ 更新 |
| `/health` 信息不足 | 正确 | 缺少 version/uptime/capabilities | 保留 |
| STT 错误分类 2 类 | 正确 | `SttServerUnavailable` + `SttServerError` | 保留 |
| 500 不区分 | 正确 | 所有异常统一 `except Exception` → `500 build_error_response(str(exc))` | 保留 |
| wake check 用调用次数 | 正确 | `_stt_call_count["n"] == 1` | 保留 |
| 30 字硬截断 | 正确 | `_shorten_reply` max_length=30 | 保留 |
| thinking disabled | **上一轮漏掉** | 源码 line 85: `"thinking": {"type": "disabled"}` | ✅ 补上 |
| request_id 缺失 | 正确 | 整个项目无 request_id | 保留 |
| 错误码不稳定 | 正确 | 错误消息是 free-form strings | 保留 |
| 没有 task_router | 正确 | 工具拦截在 `_looks_like_tool_request` in llm_reply_service | 保留 |
| 111 tests | 正确 | 实测 111 passed | 保留 |

---

## 九、真实技术债 Top 3

1. **STT server 500 裸 `str(exc)` 可能泄露内部信息**（`stt_server.py` line 86）— 当前 `/transcribe` 异常处理直接把异常字符串返回给客户端。V1.0.1 应先修这个，用 `api_error_service.build_error_response` 替换。

2. **`_overlay_stt` 调用计数 hack**（`voice_overlay.py` line 353–366）— 用闭包可变 dict + `== 1` 判断 wake/command phase。脆弱：如果 `run_wake_loop_once` 内部调用次数变化，此逻辑破裂。V1.0.3 应替换为显式 phase 参数。

3. **`voice_overlay.py` `_run_overlay_loop` 413 行单函数**（line 340–442）— 包含 wake 编排 + LLM 回复 + TTS 播放 + STT 错误处理 + cooldown。V1.0.4 应拆出 `reply_pipeline_service`。

---

## 十、V1.0.1 重新评估

### 是否仍然合适：是

V1.0.1 做 API response envelope + request_id + error codes 的方向正确。但基于源码审计，**最小范围应缩小**：

### V1.0.1 修正后最小范围

**新增文件（3 个）：**
1. `src/xiaohuang/api_schemas.py` — `ApiResponse[T]` / `ErrorDetail` dataclasses
2. `src/xiaohuang/api_error_service.py` — `ErrorCode` enum + `build_error_response()` / `build_success_response()`
3. `src/xiaohuang/request_context_service.py` — `generate_request_id()` + `RequestContext`

**修改文件（1 个）：**
4. `scripts/stt_server.py` — 仅修改异常路径（line 86: `build_error_response(str(exc))` → 使用 `ErrorCode.STT_TRANSCRIBE_FAILED`），和 `/health` 增加 `request_id`

**明确不改（V1.0.1）：**
- `scripts/voice_overlay.py` — 绝对不动
- `src/xiaohuang/stt_client_service.py` — 不动（V1.0.2 才改）
- `src/xiaohuang/llm_reply_service.py` — 不动
- `src/xiaohuang/tts_service.py` — 不动
- `src/xiaohuang/wake_loop_service.py` — 不动
- 所有其他源码文件 — 不动

### V1.0.1 不改动的理由

- `voice_overlay.py` 的 `_overlay_stt` 包装器和 `_run_overlay_loop` 在 V0.9.1 刚刚稳定，不应在 stability release 中重构
- `stt_client_service.py` 的错误分类精细化属于 V1.0.2（需要先有统一的 error code 体系才能做 client 侧分类）
- `llm_reply_service.py` 的工具拦截和 fallback 逻辑已稳定，不应破坏

### V1.0.1 不破坏 V0.9.1 链路的保证

- `stt_server.py` 修改是向后兼容的：新字段（`request_id`）对旧 client 透明
- `/health` 增加字段不影响 `check_server_health`（它只检查 `ok` 和 `error`）
- `/transcribe` 成功响应格式不变（只增加 `request_id`）
- `/transcribe` 错误响应格式从 `{"ok": false, "error": "msg"}` 变为 `{"ok": false, "request_id": "...", "error": {"code": "...", "message": "..."}, "data": null}` — 需要确认 `stt_client_service.py` 是否依赖 `error` 字段格式
- 实际检查：`stt_client_service.py` 读 `data.get("ok")` 和 `data.get("error")` — 如果 `error` 从 string 变成 dict，`str(data.get("error"))` 行为变化。**这是一个需要处理的兼容点。**

### V1.0.1 兼容性风险

**风险：** `stt_client_service.py` line 41 和 line 62:
```python
raise SttServerError(str(data.get("error", "STT server returned ok=false.")))
```
如果 `error` 从 `"Missing wav_path."`（string）变成 `{"code": "...", "message": "..."}`（dict），`str()` 会输出 dict 的 repr 而非可读消息。

**缓解：** V1.0.1 同步微调 `stt_client_service.py` 的 `SttServerError` 构造，从 `error` 字段提取 `message`。这是 1 行改动，不改变行为语义。

---

## 附录 A: 验证命令（保守清单）

```powershell
# 启动 STT server
& "F:\for_xiaohuang\conda310\python.exe" scripts/stt_server.py

# health 检查
curl http://127.0.0.1:8766/health

# 测试转写
& "F:\for_xiaohuang\conda310\python.exe" scripts/stt_client.py data/recordings/test_xxx.wav

# 唤醒测试
& "F:\for_xiaohuang\conda310\python.exe" scripts/wake_loop.py --device 0 --once --debug

# 浮窗测试
& "F:\for_xiaohuang\conda310\python.exe" scripts/voice_overlay.py --device 0 --debug

# DeepSeek fallback（无 key）
& "F:\for_xiaohuang\conda310\python.exe" scripts/voice_overlay.py --device 0 --debug --enable-llm

# TTS 播放
& "F:\for_xiaohuang\conda310\python.exe" scripts/voice_overlay.py --device 0 --debug --enable-tts

# 全量测试
& "F:\for_xiaohuang\conda310\python.exe" -m unittest discover -s tests
& "F:\for_xiaohuang\conda310\python.exe" -m compileall -q src scripts tests
```

## 附录 B: 未验证假设

1. **DeepSeek API 接受 `thinking: {type: "disabled"}` 参数** — 未在真实 DeepSeek API 上验证，基于文档推断。如果 API 返回错误，fallback 会触发 `rule_fallback_error`。
2. **edge-tts 服务可用性** — 依赖微软非官方 API。如果微软改变接口，TTS 会失败但不影响文字显示。
3. **SenseVoiceSmall 模型路径** — 假设 `MODELSCOPE_CACHE` 或 `HF_HOME` 已配置。如果模型缓存路径不存在，首次加载会下载。
