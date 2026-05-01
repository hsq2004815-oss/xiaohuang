# V1.0 Backend Foundation — Architecture Design

> **Status:** Draft for review. This document is the architecture reference; implementation is staged in `backend-foundation-plan.md`.

## 1. Current Architecture Diagnosis (V0.9.1)

### 1.1 Component Responsibilities (Current)

| File | Current Role | Problem |
|------|-------------|---------|
| `scripts/voice_overlay.py` (~470 lines) | Tkinter UI + wake loop orchestration + reply pipeline (rule/LLM) + TTS playback + STT error handling + LLM config + debug logging | **Overweight**: UI, orchestration, business logic, and I/O are all in one file |
| `scripts/stt_server.py` | HTTP server wrapping SenseVoiceSmall; serves `/health` and `/transcribe` | Response format inconsistent: `ok`/`text`/`error` fields vary; `/health` returns minimal info |
| `src/xiaohuang/stt_client_service.py` | HTTP client: `check_server_health()`, `request_transcription()` | Error classes are too coarse: `SttServerUnavailable` vs `SttServerError` don't distinguish 4xx/5xx/invalid-json |
| `src/xiaohuang/stt_server_service.py` | Server-side path guard, `build_success_response`, `build_error_response` | Responses lack `request_id`; error messages are free-form strings |
| `src/xiaohuang/stt_service.py` | SenseVoiceSmall transcriber wrapper | Model init errors and transcription errors are both `TranscriptionError`; no error code separation |
| `src/xiaohuang/wake_loop_service.py` | Wake check loop + VAD command recording orchestration | Wake check and command phases are implicit; uses call-count hack in overlay wrapper to distinguish phases |
| `src/xiaohuang/llm_reply_service.py` | DeepSeek API client + reply generation + fallback | Response parsing is robust; `thinking: disabled` confirmed in source; `max_tokens` default=256; debug summary is safe |
| `src/xiaohuang/reply_service.py` | Local rule-based reply | Clean, no issues |
| `src/xiaohuang/tts_service.py` | edge-tts synthesis | Clean, no issues |
| `src/xiaohuang/audio_playback_service.py` | Windows audio playback | Clean, no issues |

### 1.2 Identified Problems

| # | Problem | Impact | Root Cause |
|---|---------|--------|------------|
| P1 | **Overlay script is too fat** | Hard to test individual layers; UI changes risk breaking business logic | No separation between UI / orchestration / pipeline / capability layers |
| P2 | **STT API response format inconsistent** | `/health` and `/transcribe` have different shapes; error responses are free-form strings | No shared response schema; `build_success_response` and `build_error_response` are ad-hoc |
| P3 | **No `request_id`** | Cannot trace a single voice command through STT → LLM → TTS pipeline | `request_id` pattern not implemented anywhere |
| P4 | **Error codes are unstable** | Error strings change per call; client can't reliably match on error type | No error code enum or constant |
| P5 | **HTTP 500 vs connection failure not distinguished** | `SttServerError` lumps 4xx, 5xx, and invalid JSON together; `SttServerUnavailable` lumps DNS/refused/timeout | Only two exception classes for five distinct failure modes |
| P6 | **`/health` response is minimal** | Only `ok`/`status`/`server_model_init_seconds`; no version, uptime, capabilities | `/health` was built for "is it up?" not "what can it do?" |
| P7 | **Wake check vs command phase implicit** | Phase distinction relies on call-count hack in `_overlay_stt`; fragile under refactor | `run_wake_loop_once` doesn't expose phase to caller |
| P8 | **No task router or permission gate** | Tool requests are blocked by keyword match in `llm_reply_service`, but there's no architectural placeholder for future tool routing | Tool blocking is in the wrong layer (LLM reply, not task routing) |

---

## 2. V1.0 Target Architecture

### 2.1 Design Principles

1. **Modular monolith** — no microservices, no inter-process communication beyond the existing STT server process
2. **Layered** — UI → Controller → Pipeline → Capability, per database `backend-layered-architecture-rules.md`
3. **Shared schema** — every API boundary uses the same response envelope
4. **Traceable** — every request through the pipeline gets a `request_id`
5. **No premature features** — task router is designed as a placeholder, not implemented

### 2.2 Target Component Map

```
┌──────────────────────────────────────────────────────────┐
│                  Desktop UI Layer                         │
│  scripts/voice_overlay.py  (Tkinter, ~150 lines)         │
│  - Window management only                                │
│  - Delegates all logic to overlay_controller_service     │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│               Controller Layer                            │
│  src/xiaohuang/overlay_controller_service.py             │
│  - Wake loop orchestration                               │
│  - Phase state machine (idle→wake→listen→transcribe→     │
│    reply→speak→result)                                   │
│  - Delegates to reply_pipeline_service                   │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│               Pipeline Layer                              │
│  src/xiaohuang/reply_pipeline_service.py                 │
│  - Orchestrates STT → LLM → TTS flow                     │
│  - Fallback decision logic                               │
│  - reply_source tracking                                 │
└────┬──────────────┬──────────────┬───────────────────────┘
     │              │              │
┌────▼────┐  ┌──────▼──────┐  ┌──▼───────────────────────┐
│  STT    │  │    LLM      │  │  TTS / Audio              │
│ Cap.    │  │   Cap.      │  │  Cap.                     │
│         │  │             │  │                           │
│ stt_api │  │ llm_reply   │  │ tts_service               │
│ _service│  │ _service    │  │ audio_playback_service    │
│         │  │ reply_      │  │                           │
│ stt_cli │  │ service     │  │                           │
│ ent_serv│  │             │  │                           │
│ ice     │  │             │  │                           │
│         │  │             │  │                           │
│ stt_ser │  │             │  │                           │
│ ver_serv│  │             │  │                           │
│ ice     │  │             │  │                           │
└─────────┘  └─────────────┘  └───────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│               Shared / Core Layer                         │
│  api_schemas.py         — request/response DTOs          │
│  api_error_service.py   — error codes + error response   │
│  request_context_       — request_id generation          │
│    service.py                                            │
│  task_router_service.py — future tool routing placeholder│
└──────────────────────────────────────────────────────────┘
```

### 2.3 New Files (V1.0 adds)

| File | Purpose | Phase |
|------|---------|-------|
| `src/xiaohuang/api_schemas.py` | `ApiRequest` / `ApiResponse[T]` / `ErrorDetail` dataclasses | V1.0.1 |
| `src/xiaohuang/api_error_service.py` | `ErrorCode` enum, `build_error_response()` | V1.0.1 |
| `src/xiaohuang/request_context_service.py` | `generate_request_id()`, `RequestContext` | V1.0.1 |
| `src/xiaohuang/stt_api_service.py` | New STT client with fine-grained error types (wraps `stt_client_service.py`) | V1.0.2 |
| `src/xiaohuang/reply_pipeline_service.py` | Extracted from voice_overlay.py `_run_overlay_loop` reply logic | V1.0.4 |
| `src/xiaohuang/overlay_controller_service.py` | Extracted from voice_overlay.py wake loop orchestration | V1.0.3 |
| `src/xiaohuang/task_router_service.py` | Placeholder with `route_task()` stub, no implementation | V1.0.5 |

### 2.4 Existing Files Modified

| File | Change | Phase |
|------|--------|-------|
| `scripts/stt_server.py` | Use `api_schemas` / `api_error_service` / `request_context_service` | V1.0.1 |
| `src/xiaohuang/stt_client_service.py` | Split into fine-grained error classes | V1.0.2 |
| `src/xiaohuang/stt_server_service.py` | Use shared response builders | V1.0.1 |
| `scripts/voice_overlay.py` | Slim down to UI + delegation (~150 lines) | V1.0.3–V1.0.4 |

---

## 3. Unified API Response Format

### 3.1 Success

```json
{
  "ok": true,
  "request_id": "req_20260501_a1b2c3d4",
  "data": { ... },
  "error": null
}
```

### 3.2 Error

```json
{
  "ok": false,
  "request_id": "req_20260501_a1b2c3d4",
  "data": null,
  "error": {
    "code": "STT_FILE_NOT_FOUND",
    "message": "WAV file not found: data/recordings/test.wav",
    "detail": null
  }
}
```

### 3.3 Python Schema

```python
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")

@dataclass
class ErrorDetail:
    code: str
    message: str
    detail: str | None = None

@dataclass
class ApiResponse(Generic[T]):
    ok: bool
    request_id: str
    data: T | None = None
    error: ErrorDetail | None = None
```

---

## 4. Error Code Design

### 4.1 Error Code Enum

```python
from enum import Enum

class ErrorCode(str, Enum):
    # STT errors
    STT_MISSING_WAV_PATH = "STT_MISSING_WAV_PATH"
    STT_INVALID_WAV_PATH = "STT_INVALID_WAV_PATH"
    STT_FILE_NOT_FOUND = "STT_FILE_NOT_FOUND"
    STT_TRANSCRIBE_FAILED = "STT_TRANSCRIBE_FAILED"
    STT_MODEL_UNAVAILABLE = "STT_MODEL_UNAVAILABLE"
    STT_SERVER_INTERNAL_ERROR = "STT_SERVER_INTERNAL_ERROR"

    # General API errors
    INVALID_JSON = "INVALID_JSON"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    ROUTE_NOT_FOUND = "ROUTE_NOT_FOUND"

    # Future
    LLM_API_ERROR = "LLM_API_ERROR"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    TTS_SYNTHESIS_FAILED = "TTS_SYNTHESIS_FAILED"
    TASK_NOT_IMPLEMENTED = "TASK_NOT_IMPLEMENTED"
```

### 4.2 Error Code Mapping

| Scenario | Code | HTTP Status |
|----------|------|-------------|
| wav_path missing from request body | `STT_MISSING_WAV_PATH` | 400 |
| wav_path outside allowed directory | `STT_INVALID_WAV_PATH` | 400 |
| wav_path does not exist on disk | `STT_FILE_NOT_FOUND` | 404 |
| FunASR generate() raised exception | `STT_TRANSCRIBE_FAILED` | 500 |
| SenseVoiceSmall model not loaded | `STT_MODEL_UNAVAILABLE` | 503 |
| Unhandled server error | `STT_SERVER_INTERNAL_ERROR` | 500 |
| Request body is not valid JSON | `INVALID_JSON` | 400 |
| Wrong HTTP method | `METHOD_NOT_ALLOWED` | 405 |
| Unknown route | `ROUTE_NOT_FOUND` | 404 |

---

## 5. `/health` Enhancement

### 5.1 Current (V0.9.1, 源码确认)

```json
{
  "ok": true,
  "status": "ready",
  "server_model_init_seconds": 24.75
}
```

注：当前 `/health` 无 `error` 字段、无 `request_id`、无 `version`/`uptime`/`capabilities`。

### 5.2 V1.0 Target

```json
{
  "ok": true,
  "request_id": "req_20260501_a1b2c3d4",
  "data": {
    "status": "ok",
    "version": "1.0.0",
    "uptime_seconds": 3600.5,
    "model_name": "iic/SenseVoiceSmall",
    "server_model_init_seconds": 24.75,
    "port": 8766,
    "capabilities": ["transcribe", "health"]
  },
  "error": null
}
```

### 5.3 Rules

- `/health` must NOT expose: local file paths, API keys, environment variable values, model cache paths
- `capabilities` list is stable and versioned

---

## 6. STT Client Error Classification

### 6.1 Current (V0.9.1)

```
SttServerUnavailable  — DNS failure, connection refused, timeout
SttServerError        — HTTP 4xx, HTTP 5xx, ok=false, invalid JSON
```

### 6.2 V1.0 Target

```python
class SttServerUnavailable(RuntimeError):
    """Cannot reach the STT server at all (DNS, refused, timeout)."""

class SttRequestError(RuntimeError):
    """Server returned HTTP 4xx."""

class SttServerInternalError(RuntimeError):
    """Server returned HTTP 5xx."""

class SttApiError(RuntimeError):
    """Server returned HTTP 200 but ok=false in body."""

class SttInvalidResponse(RuntimeError):
    """Server returned non-JSON or unparseable body."""
```

### 6.3 Classification Logic

```
try:
    response = urlopen(...)
except HTTPError as e:
    if 400 <= e.code < 500: raise SttRequestError
    if 500 <= e.code < 600: raise SttServerInternalError
except (URLError, TimeoutError, OSError):
    raise SttServerUnavailable

try:
    data = json.loads(body)
except JSONDecodeError:
    raise SttInvalidResponse

if not data.get("ok"):
    raise SttApiError(data.get("error", {}).get("code", "UNKNOWN"))
```

---

## 7. Overlay Scheduling Split Plan

### 7.1 Target: voice_overlay.py (~150 lines)

```python
# scripts/voice_overlay.py  (after V1.0.4)
def main():
    args = parse_args()
    config = load_config()
    logger = configure_logging(...)

    root = tk.Tk()
    app = VoiceOverlayApp(root, stop_event=stop_event)
    controller = OverlayController(app=app, options=options, config=config, logger=logger)

    worker = threading.Thread(target=controller.run, daemon=True)
    worker.start()
    root.mainloop()
    controller.shutdown()
```

### 7.2 Layer Responsibilities

| Layer | File | Responsibility |
|-------|------|---------------|
| **UI** | `voice_overlay.py` | Tkinter window, animation, drag, close/safe_after |
| **UI State** | `overlay_state_service.py` | Status text mapping (no change) |
| **Controller** | `overlay_controller_service.py` | Wake loop, phase state machine, delegate to pipeline |
| **Pipeline** | `reply_pipeline_service.py` | STT→LLM→TTS orchestration, fallback decision, source tracking |
| **Capability** | `stt_api_service.py`, `llm_reply_service.py`, `tts_service.py` | Individual capability calls, each with own error handling |
| **Shared** | `api_schemas.py`, `api_error_service.py`, `request_context_service.py` | Cross-cutting concerns |

### 7.3 Phase State Machine

```
IDLE → WAKE_CHECKING → WAKE_DETECTED → LISTENING → TRANSCRIBING → REPLYING → SPEAKING → RESULT → IDLE
                                                                                    ↳ ERROR → IDLE
```

Each phase transition is an explicit method on `OverlayController`, not a callback inside a while loop.

---

## 8. Staged Implementation Plan

| Version | Scope | Files New | Files Modified | Tests |
|---------|-------|-----------|---------------|-------|
| **V1.0.1** | API response envelope + request_id + error codes | `api_schemas.py`, `api_error_service.py`, `request_context_service.py` | `stt_server.py`, `stt_server_service.py` | `/health` schema, `/transcribe` error codes, request_id presence |
| **V1.0.2** | Enhanced /health + STT client error classification | `stt_api_service.py` | `stt_client_service.py`, `stt_server.py` | 5 error types, `/health` version/capabilities |
| **V1.0.3** | Phase state machine, remove call-count hack | `overlay_controller_service.py` | `voice_overlay.py`, `wake_loop_service.py` | Phase transitions, STT 500 per phase |
| **V1.0.4** | Extract reply_pipeline_service | `reply_pipeline_service.py` | `voice_overlay.py` | Pipeline unit tests, TTS fallback isolation |
| **V1.0.5** | Task router placeholder + integration tests | `task_router_service.py` | — | Integration tests across pipeline |

### 8.1 Why This Order

1. **V1.0.1 first**: schema and error codes are zero-risk. They're additive — old code continues to work, new code uses them. This establishes the shared layer that everything else builds on.
2. **V1.0.2 next**: enhanced `/health` is low-risk and gives immediate observability value. STT client error classification enables proper error handling in later phases.
3. **V1.0.3–V1.0.4**: structural refactors that are safe because the shared layer (V1.0.1–V1.0.2) already provides consistent error boundaries.
4. **V1.0.5 last**: task router placeholder is purely additive; no behavior change.

---

## 9. Test Plan

### 9.1 Per-Version Test Matrix

**V1.0.1:**
- `/health` returns `ok`/`request_id`/`data.status` in unified format
- `/transcribe` without `wav_path` → `STT_MISSING_WAV_PATH` (400)
- `/transcribe` with non-`.wav` path → `STT_INVALID_WAV_PATH` (400)
- `/transcribe` with path outside `data/recordings/` → `STT_INVALID_WAV_PATH` (400)
- `/transcribe` with missing file → `STT_FILE_NOT_FOUND` (404)
- `/transcribe` with FunASR error → `STT_TRANSCRIBE_FAILED` (500)
- Every response includes `request_id`
- 500 errors do not leak traceback in response body
- `voice_overlay.py --help` unchanged
- `wake_loop.py --help` unchanged

**V1.0.2:**
- `/health` returns `version`/`uptime_seconds`/`model_name`/`capabilities`
- `/health` does NOT leak local paths or env values
- STT client raises `SttServerUnavailable` on connection refused
- STT client raises `SttRequestError` on HTTP 400
- STT client raises `SttServerInternalError` on HTTP 500
- STT client raises `SttApiError` on `ok=false` response
- STT client raises `SttInvalidResponse` on non-JSON body

**V1.0.3:**
- Wake check STT 500 → phase stays in WAKE_CHECKING, retries next window
- Command STT 500 → phase transitions to ERROR, overlay shows error state
- Phase transitions are deterministic (not call-count dependent)
- `_overlay_stt` wrapper removed

**V1.0.4:**
- `reply_pipeline_service` unit-testable without Tkinter
- LLM fallback logic isolated from UI
- TTS failure does not affect text display

**V1.0.5:**
- `task_router_service.route_task()` returns `(False, "TASK_NOT_IMPLEMENTED")` for all inputs
- Integration test: full pipeline from wake to reply with mock STT/LLM/TTS
- All 111 existing tests still pass

---

## 10. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| STT server API changes break wake_loop.py | Medium | High | `wake_loop.py` also updated in V1.0.1; add backward-compat test |
| Overlay refactor (V1.0.3–V1.0.4) introduces regression | Medium | Medium | Keep old voice_overlay.py working until new controller passes same manual test flow |
| Error code enum grows too large | Low | Low | Only add codes when a distinct error scenario is confirmed |
| Task router placeholder creates false expectation | Low | Low | Docstring explicitly states "not implemented; returns TASK_NOT_IMPLEMENTED for all inputs" |
