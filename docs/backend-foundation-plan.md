# V1.0 Backend Foundation — Implementation Plan

> **Status:** Draft for review. Companion to `backend-foundation.md`. Each version below is self-contained and ships with tests.

---

## Version Outline

| Version | Summary | Risk | Est. files |
|---------|---------|------|------------|
| V1.0.1 | API response envelope + request_id + error codes | Low | 3 new, 2 modified |
| V1.0.2 | Enhanced /health + STT client error classification | Low | 1 new, 2 modified |
| V1.0.3 | Phase state machine, remove call-count hack | Medium | 1 new, 2 modified |
| V1.0.4 | Extract reply_pipeline_service | Medium | 1 new, 1 modified |
| V1.0.5 | Task router placeholder + integration tests | Low | 1 new, 0 modified |

---

## V1.0.1 — API Response Envelope + request_id + Error Codes

### Goal
Every API boundary (STT server, future local API) uses the same response shape. Every request gets a `request_id`. Error codes are stable enums.

### New Files

**`src/xiaohuang/api_schemas.py`**
```python
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

**`src/xiaohuang/api_error_service.py`**
```python
class ErrorCode(str, Enum):
    STT_MISSING_WAV_PATH = "STT_MISSING_WAV_PATH"
    STT_INVALID_WAV_PATH = "STT_INVALID_WAV_PATH"
    STT_FILE_NOT_FOUND = "STT_FILE_NOT_FOUND"
    STT_TRANSCRIBE_FAILED = "STT_TRANSCRIBE_FAILED"
    STT_MODEL_UNAVAILABLE = "STT_MODEL_UNAVAILABLE"
    STT_SERVER_INTERNAL_ERROR = "STT_SERVER_INTERNAL_ERROR"
    INVALID_JSON = "INVALID_JSON"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    ROUTE_NOT_FOUND = "ROUTE_NOT_FOUND"

def build_error_response(code: ErrorCode, message: str, *, detail: str | None = None) -> dict:
    ...

def build_success_response(data: Any) -> dict:
    ...
```

**`src/xiaohuang/request_context_service.py`**
```python
def generate_request_id() -> str:
    """Returns 'req_' + timestamp + random hex, e.g. req_20260501_a1b2c3d4."""

@dataclass
class RequestContext:
    request_id: str
    start_time: float
```

### Modified Files

**`src/xiaohuang/stt_server_service.py`**
- `build_success_response()` → delegates to `api_error_service.build_success_response()`
- `build_error_response()` → delegates to `api_error_service.build_error_response()`
- `resolve_recording_wav_path()` → raises typed exceptions that map to `ErrorCode`

**`scripts/stt_server.py`**
- Each route handler creates a `RequestContext`
- Error paths use `build_error_response(ErrorCode.XXX, ...)`
- `/health` returns unified response format

### Tests
- `/health` returns `ok`/`request_id`/`data.status`
- `/transcribe` without `wav_path` → `STT_MISSING_WAV_PATH`, HTTP 400
- `/transcribe` with non-`.wav` path → `STT_INVALID_WAV_PATH`, HTTP 400
- `/transcribe` with path traversal → `STT_INVALID_WAV_PATH`, HTTP 400
- `/transcribe` with missing file → `STT_FILE_NOT_FOUND`, HTTP 404
- `/transcribe` with FunASR model error → `STT_TRANSCRIBE_FAILED`, HTTP 500
- All responses include `request_id`
- 500 responses do NOT contain traceback
- `voice_overlay.py --help` output unchanged
- `wake_loop.py --help` output unchanged
- Existing 111 tests still pass

### Verification
```powershell
& "F:\for_xiaohuang\conda310\python.exe" -m unittest discover -s tests
& "F:\for_xiaohuang\conda310\python.exe" -m compileall -q src scripts tests
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --help
& "F:\for_xiaohuang\conda310\python.exe" scripts\wake_loop.py --help
```

---

## V1.0.2 — Enhanced /health + STT Client Error Classification

### Goal
`/health` becomes a useful diagnostic endpoint. STT client distinguishes 5 error types instead of 2.

### New Files

**`src/xiaohuang/stt_api_service.py`**
```python
class SttServerUnavailable(RuntimeError): ...
class SttRequestError(RuntimeError): ...
class SttServerInternalError(RuntimeError): ...
class SttApiError(RuntimeError): ...
class SttInvalidResponse(RuntimeError): ...

def check_server_health(server_url, timeout=5.0) -> dict:
    # Uses new error classes
    ...

def request_transcription(wav_path, server_url, timeout=120.0) -> dict:
    # Uses new error classes
    ...
```

### Modified Files

**`src/xiaohuang/stt_client_service.py`**
- Deprecate old `check_server_health` and `request_transcription`
- Re-export from `stt_api_service` for backward compatibility

**`scripts/stt_server.py`**
- `/health` returns `version`, `uptime_seconds`, `model_name`, `server_model_init_seconds`, `port`, `capabilities`
- `/health` does NOT expose file paths, env values, or API keys

### Tests
- `/health` returns `version`, `uptime_seconds`, `model_name`, `capabilities`
- `/health` does NOT leak paths or env values
- `SttServerUnavailable` raised on connection refused
- `SttRequestError` raised on HTTP 400
- `SttServerInternalError` raised on HTTP 500
- `SttApiError` raised on `ok=false` in body
- `SttInvalidResponse` raised on non-JSON body
- `voice_overlay.py` and `wake_loop.py` continue to work (they import from `stt_client_service` which re-exports)

---

## V1.0.3 — Phase State Machine

### Goal
Eliminate the call-count hack in `_overlay_stt`. Wake check and command transcription are explicit phases. Each phase has its own error handling policy.

### New Files

**`src/xiaohuang/overlay_controller_service.py`**
```python
class OverlayPhase(Enum):
    IDLE = "idle"
    WAKE_CHECKING = "wake_checking"
    WAKE_DETECTED = "wake_detected"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    REPLYING = "replying"
    SPEAKING = "speaking"
    RESULT = "result"
    ERROR = "error"

@dataclass
class OverlayController:
    app: VoiceOverlayApp
    options: WakeLoopOptions
    pipeline: ReplyPipelineService  # or inline until V1.0.4
    phase: OverlayPhase = OverlayPhase.IDLE
    ...

    def run(self):
        while not self._stop_event.is_set():
            self._run_wake_check_phase()
            if not self._wake_detected:
                continue
            self._run_command_phase()

    def _run_wake_check_phase(self):
        """STT 500 here → log warning, skip window, stay in WAKE_CHECKING."""
        ...

    def _run_command_phase(self):
        """STT 500 here → transition to ERROR, show overlay error."""
        ...
```

### Modified Files

**`scripts/voice_overlay.py`**
- `_run_overlay_loop` function replaced by `OverlayController.run()`
- `_overlay_stt` wrapper removed
- `_make_llm_debug_handler` and `_source_note_for_overlay` move to controller

**`src/xiaohuang/wake_loop_service.py`**
- No functional change needed, but `run_wake_loop_once` may get an optional `phase_callback` parameter

### Tests
- Wake check STT 500 → stays in WAKE_CHECKING, no crash
- Command STT 500 → transitions to ERROR, overlay shows error
- Phase transitions follow deterministic sequence (no call-count dependency)
- Debug output shows phase transitions
- Existing wake_loop.py console mode still works

---

## V1.0.4 — Extract Reply Pipeline Service

### Goal
The reply logic (STT → rule/LLM fallback → TTS) is extractable from the overlay loop. It becomes independently testable without Tkinter.

### New Files

**`src/xiaohuang/reply_pipeline_service.py`**
```python
@dataclass
class ReplyPipelineResult:
    reply_text: str
    reply_source: str
    source_note: str | None
    tts_path: Path | None
    tts_error: str | None

@dataclass
class ReplyPipeline:
    enable_llm: bool
    llm_config: LlmReplyConfig
    enable_tts: bool
    tts_voice: str
    tts_output_dir: Path
    on_debug: Callable[[str], None] | None = None

    def generate_reply_and_tts(self, command_text: str) -> ReplyPipelineResult:
        ...
```

### Modified Files

**`scripts/voice_overlay.py`**
- Reply logic in `_run_overlay_loop` replaced by `self.pipeline.generate_reply_and_tts(result.command_text)`
- `_run_overlay_loop` becomes the controller's `run()` method

### Tests
- `ReplyPipeline` unit-testable with mock STT result (no Tkinter needed)
- LLM fallback logic produces correct `reply_source`
- TTS failure sets `tts_error` but `reply_text` is still populated
- Source notes match V0.9.1 behavior
- Existing overlay behavior unchanged

---

## V1.0.5 — Task Router Placeholder + Integration Tests

### Goal
Add the architectural placeholder for future tool execution. Add integration tests across the full pipeline. No tool execution is implemented.

### New Files

**`src/xiaohuang/task_router_service.py`**
```python
@dataclass
class TaskRouteResult:
    can_execute: bool
    reason: str  # "not_implemented", "permission_denied", etc.
    suggested_action: str | None = None

def route_task(user_text: str) -> TaskRouteResult:
    """
    Placeholder for future task routing.
    Always returns (False, "not_implemented") — no tasks are implemented yet.
    """
    return TaskRouteResult(can_execute=False, reason="not_implemented")
```

### Modified Files
None. This is purely additive.

### Tests
- `route_task("打开浏览器")` → `(False, "not_implemented")`
- `route_task("你好")` → `(False, "not_implemented")`
- Integration test: mock STT + mock LLM + mock TTS → full pipeline from wake to reply
- All existing 111+ tests still pass

---

## Appendix A: Verification Checklist (Each Version)

```powershell
# After every version:
& "F:\for_xiaohuang\conda310\python.exe" -m unittest discover -s tests
& "F:\for_xiaohuang\conda310\python.exe" -m compileall -q src scripts tests
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --help
& "F:\for_xiaohuang\conda310\python.exe" scripts\wake_loop.py --help
```

## Appendix B: Files NOT Touched in Any V1.0 Version

- `E:\DataBase` — read-only
- `src/xiaohuang/audio_capture_service.py` — stable V0.8
- `src/xiaohuang/vad_service.py` — stable V0.8
- `src/xiaohuang/vad_recording_service.py` — stable V0.8
- `src/xiaohuang/wake_word_service.py` — stable V0.7.2
- `src/xiaohuang/config_service.py` — stable
- `src/xiaohuang/logging_service.py` — stable
- `src/xiaohuang/reply_service.py` — stable V0.9
- `src/xiaohuang/tts_service.py` — stable V0.9, user confirmed no changes
- `src/xiaohuang/audio_playback_service.py` — stable V0.9, user confirmed no changes
- `src/xiaohuang/overlay_state_service.py` — stable V0.9.1
- `src/xiaohuang/overlay_runtime_service.py` — stable V0.9.1
- `src/xiaohuang/listen_once_service.py` — stable V0.8
- `scripts/check_audio_devices.py` — stable
- `scripts/record_test.py` — stable
- `scripts/listen_once.py` — stable
- `scripts/transcribe_test.py` — stable
- `scripts/run_env.ps1` — stable
- `scripts/test_wake_text.py` — stable
- `config/xiaohuang.yaml` — stable
- `.gitignore` — stable
- `requirements.txt` — stable (no new deps in V1.0)

## Appendix C: Rollback Strategy

Each V1.0.x version is committed separately. Rollback is `git revert <commit>` for that version. Because each version is self-contained:
- V1.0.1 can be reverted without affecting V1.0.2–V1.0.5 (they build on it)
- V1.0.3 can be reverted independently (overlay falls back to V1.0.2 call-count style)
