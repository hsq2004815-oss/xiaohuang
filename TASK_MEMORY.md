# Task Memory

## Current Snapshot（2026-05-10）— V1.5-C0 Natural Language Action Task Safety Design Doc

- Purpose: Upgrade the task model from "text task" to "voice-or-text natural language task" and design the safety boundaries for action-type tasks. Design only — no code changes.
- Key files: `docs/natural-language-action-task-safety-design.md` (new, 20 sections), `TASK_MEMORY.md` (updated).
- Last completed:
  1. Concept upgrade: text task → natural language task, unified flow for both voice and text input sources.
  2. Safety rules for voice: wake word ≠ authorization, ASR transcript ≠ trusted command, all action tasks must go through pending registry + user confirmation.
  3. Action categories: readonly / safe_action / controlled_action / dangerous_action.
  4. Risk levels: low / medium / high / blocked, with voice-specific escalation (low-confidence voice → medium, vague dangerous intent → blocked).
  5. ASR confidence design: high/medium/low thresholds, requires_reconfirm flag, transcript saved but audio never persisted.
  6. Voice confirmation words: must bind to active task_id, cannot confirm expired/blocked tasks, multiple pending tasks require disambiguation.
  7. Prohibited automation list: 17 items (delete files, shell commands, registry changes, messaging, payments, etc.) — all blocked in C phase.
  8. C1 scope: 4 safe local open actions (open logs dir, config dir, project dir, task history dir) — all whitelist path-based, never user-specified paths. Voice or text trigger with mandatory confirmation.
  9. Pending registry / task history / runtime events integration rules documented.
  10. UI confirmation card field design with source-specific fields (transcript, asr_confidence for voice).
  11. Bounded decisions: 12 rules locking down C-phase constraints. text_task_* naming retained short-term, no rename.
- Verification: git diff --check OK; git status clean (only 2 doc files changed). No code was modified.
- Known traps: C0 is design only — implementation begins at C1. All text_task_* files retain current names.

## Current Snapshot（2026-05-10）— V1.5-B2.4 Task History Section Isolation Fix

- Purpose: Fix task history content leaking onto Home page — `tasks-history-shell` class on `<section>` element was overriding `content-section`'s `display:none` with `display:flex`.
- Key files: `frontend/control_panel/index.html` (moved shell class to inner div wrapper), `tests/test_control_panel_web_service.py` (+2 isolation tests).
- Last completed:
  1. HTML: Changed `<section class="content-section tasks-history-shell" id="section-tasks">` → `<section class="content-section" id="section-tasks"><div class="tasks-history-shell">`. Shell is now an inner wrapper that only handles internal layout.
  2. Root cause: `.tasks-history-shell { display:flex }` appeared after `.content-section { display:none }` in CSS, and both selectors have equal specificity, so shell's `display:flex` won and the Tasks section was always visible.
  3. Fix: Section now only has `content-section` class — `display:none` hides it when not active. Inner `tasks-history-shell` div handles flex layout only when the section is active.
  4. All B2 features preserved: card click, detail panel, health report structured display, independent scrolling, loading/error/empty states, refresh button.
- Verification: compileall OK; unittest discover OK (1022 tests, 1 symlink-permission skip, +2 new); control_panel_web --help OK; voice_overlay --help OK; diff check OK.
- Known traps: Never put layout classes (display:flex/grid) on `content-section` elements — they override the show/hide toggle. Always use an inner wrapper div.

## Current Snapshot（2026-05-10）— V1.5-B2.3 Task History Independent Scroll Containers

- Purpose: Fix Tasks page scroll behavior — left list and right detail must each scroll independently without pushing the page shell taller.
- Key files: `frontend/control_panel/index.html` (added pane+scroll wrapper divs), `frontend/control_panel/assets/app.js` (updated render targets from tasks-history-list→tasks-history-list-scroll, detail→tasks-history-detail-scroll), `frontend/control_panel/assets/style.css` (height constraints + independent scroll rules), `tests/test_control_panel_web_service.py` (+2 new CSS/HTML tests).
- Last completed:
  1. HTML: Wrapped `tasks-history-list` in `tasks-history-list-pane → tasks-history-list-scroll`; wrapped `tasks-history-detail` in `tasks-history-detail-pane → tasks-history-detail-scroll`. Placeholder text moved into scroll container.
  2. JS: `renderTaskHistory()` now targets `#tasks-history-list-scroll`; `renderTaskHistoryDetail()` targets `#tasks-history-detail-scroll`; `initTaskHistory()` click delegation on scroll container.
  3. CSS: `.tasks-history-shell` has `height:100%` + `overflow:hidden`; `.tasks-history-grid` has `flex:1 1 auto` + `min-height:0` + `overflow:hidden`; pane classes enforce `min-height:0` + `overflow:hidden` + `display:flex; flex-direction:column`; scroll classes have `flex:1 1 auto` + `min-height:0` + `overflow-y:auto`.
  4. Grid columns widened slightly: `minmax(320px,0.95fr) minmax(420px,1.15fr)`.
  5. All B2/B2.1/B2.2 features preserved: card click, empty/error/loading states, health report structured display, muted raw summary, badge labels.
- Verification: compileall OK; unittest discover OK (1020 tests, 1 symlink-permission skip, +2 new); control_panel_web --help OK; voice_overlay --help OK; diff check OK.
- Known traps: Parent chain in content-section needs min-height:0 propagation; grid must have overflow:hidden to contain children; scroll containers need explicit flex:1 to fill available space.

## Current Snapshot（2026-05-10）— V1.5-B2.2 Task History Readability Polish

- Purpose: Improve task history page readability — distinguish task status from report signal, structure health report details into sections, improve detail panel layout.
- Key files: `frontend/control_panel/assets/app.js` (badge rework, health report parser, detail restructure), `frontend/control_panel/assets/style.css` (+70 lines: badge-row, detail blocks, muted raw), `tests/test_control_panel_web_service.py` (+4 new tests).
- Last completed:
  1. Card badge row: task status now labeled "任务：完成/失败", report signal now "报告：正常/有警告/有错误/信息不足", separate badge row below title. No more confusion between "完成" and "有错误".
  2. Detail header: shows both "任务：完成" and "报告：有错误" badges side-by-side, not just a single signal badge.
  3. Health report parser: `parseHealthReportSections()` uses regex markers to split compacted excerpt into 7 sections (总体状态/基础状态/配置状态/运行事件/历史日志/代表性问题/建议), each capped at 240 chars. Falls back to single "安全详情" section if no markers found.
  4. `buildHistoryInsightSections(item)` dispatches to `parseHealthReportSections` for health_report type, generic summary+safe_details fallback for others.
  5. `renderHistoryInsightBlocks(sections)` renders each section as a titled block, body capped at 400 chars, all escapeHtml'd.
  6. Detail layout: header badges → status overview (type/risk/time/files/tags) → insight blocks → raw safe summary (muted, 50% opacity, max 180px scroll) → history_id.
  7. CSS: `.task-history-badge-row`, `.tasks-history-detail-block`, `.tasks-history-detail-block-title/body`, `.tasks-history-detail-overview`, `.tasks-history-detail-muted`.
- Verification: compileall OK; unittest discover OK (1018 tests, 1 symlink-permission skip, +4 new); control_panel_web --help OK; voice_overlay --help OK; diff check OK.
- Known traps: Health report parser works on already compacted (single-line) excerpt — uses regex position indexing, not line-based parsing. All backend files unchanged.

## Current Snapshot（2026-05-10）— V1.5-B2.1 Task History UI Error State and Escaping Polish

- Purpose: Two small fixes over B2 — error/grid state mutual exclusion (was showing both on API failure), and read_files_count escaping (was raw number concatenation).
- Key files: `frontend/control_panel/assets/app.js` (refactored state management + added getHistoryReadFilesCount helper), `tests/test_control_panel_web_service.py` (+4 new B2.1 tests).
- Last completed:
  1. Replaced `showTaskHistoryLoading(on)` / `showTaskHistoryError(on)` pair with unified `setTaskHistoryViewState(state)` — guarantees exactly one of loading/error/empty/grid is visible.
  2. `loadTaskHistory()` now uses `setTaskHistoryViewState` at every branch: loading on start, grid on success with items, empty on success without items, error on API failure or non-ok response.
  3. `renderTaskHistory()` no longer manipulates empty/error display — state management is centralized in `loadTaskHistory()`.
  4. Added `getHistoryReadFilesCount(item)` helper — safe String conversion with undefined/null handling.
  5. `read_files_count` now always goes through `escapeHtml(getHistoryReadFilesCount(item))` in both list meta and detail panel.
  6. No feature creep verified: no task-history-search/delete/pagination/export in JS.
- Verification: compileall OK; unittest discover OK (1014 tests, 1 symlink-permission skip, +4 new); control_panel_web --help OK; voice_overlay --help OK; diff check OK.
- Known traps: `finally` block no longer calls any show/hide function that could overwrite error state; state function uses simple display toggle — all 4 elements toggled each call.

## Current Snapshot（2026-05-10）— V1.5-B2 Task History Tasks Page UI

- Purpose: Implement the Tasks page as the main task history entry point — list + detail panel. No search, no pagination, no Chat rail changes.
- Key files: `frontend/control_panel/index.html` (Tasks section replaced), `frontend/control_panel/assets/app.js` (+~160 lines: load/render/select/detail/signal/time helpers), `frontend/control_panel/assets/style.css` (+~200 lines: tasks-history-* classes), `tests/test_control_panel_web_service.py` (+11 new B2 UI tests, +1 old test updated).
- Last completed:
  1. HTML: Replaced Tasks placeholder with `tasks-history-shell` layout — header (title + refresh button), `tasks-history-grid` (list + detail panel), loading/empty/error states all inline.
  2. JS: `loadTaskHistory()` calls `get_recent_task_history({limit:20})` API; `renderTaskHistory()` renders cards with title + status badge + summary (2-line clamp) + meta (signal, time, tags, file count); `selectTaskHistoryItem()` + `renderTaskHistoryDetail()` show safe detail panel on click. Auto-loads on `switchSection('tasks')`. Refresh button wired.
  3. Signal parsing: `getHistorySignal(item)` extracts "正常/有警告/有错误/信息不足/失败/完成" from summary + excerpt text; displayed as color-coded badge (signal-ok/warn/err/unknown).
  4. Time: `formatHistoryTime()` (absolute) + `formatHistoryRelativeTime()` ("2分钟前") — zero dependencies.
  5. Safety: All fields escapeHtml'd; no `dangerouslySetInnerHTML`; no `task_results.jsonl` reference in frontend; no raw details/log/traceback; no local paths leaked.
  6. CSS: Dark glass theme consistent with UI0; grid layout `minmax(320px,0.9fr) minmax(360px,1.1fr)`; active card border highlight; detail panel with sections; signal badges in 4 colors.
  7. Chat: Completely untouched — no `chat-recent-tasks` class or any Chat rail modification.
- Verification: compileall OK; unittest discover OK (1010 tests, 1 symlink-permission skip, +11 new); control_panel_web --help OK; voice_overlay --help OK; diff check OK.
- Known traps: `task-status-grid` and `task-status-card` old CSS classes remain in style.css for backwards compatibility but are no longer referenced in HTML; 任务中心 → 任务历史 label change updated in existing test.

## Current Snapshot（2026-05-10）— V1.5-B1.1 Task History Path Isolation, Read API, and Layout Plan

- Purpose: Fix B1 path isolation bug (different project_root could write to wrong JSONL), add backend read API for task history, and document B2/B3 UI layout plan.
- Key files: `src/xiaohuang/task_result_history_service.py` (refactored path isolation), `src/xiaohuang/control_panel_web_service.py` (+get_recent_task_history API), `docs/task-result-history-design.md` (+layout plan section), tests.
- Last completed:
  1. Path isolation: replaced `_history_path` with `_cache_project_root` tracking. Added `_ensure_cache_for_root()` that auto-switches cache when project_root changes. `append_task_result()` and `get_recent_task_results()` always use the passed-in project_root for file path calculation. Removed invalid `pass` branch.
  2. Read API: `ControlPanelWebApi.get_recent_task_history(payload)` — default limit=20, min=1, max=50. Non-numeric/negative/oversized values clamped safely. File not exists returns `ok=True, items=[]`. Response does not leak file paths.
  3. Layout plan documented: Tasks page is main history entry point (list + detail panel). Chat right rail only shows 5 recent entries as lightweight shortcut. Task card fields: title + status badge + summary (1-2 lines) + time + tags + read_files_count. Detail panel shows safe fields only. B2 = Tasks page list first, B3 = Chat rail + tags filtering + search.
  4. 3 new path isolation tests (two roots, cross-contamination prevention). 6 new read API tests (items return, empty root, limit clamping, negative/string limit safety, no path leaks). 2 new module boundary tests (text_task_execution_service does not import task_result_history_service, frontend unchanged).
- Verification: compileall OK; unittest discover OK (999 tests, 1 symlink-permission skip, +10 new); control_panel_web --help OK; voice_overlay --help OK; diff check OK.
- Known traps: Single-cache approach (plan A) sufficient for single process model; `_ensure_cache_for_root` triggers on every call but init_task_history is fast with small files; no frontend changes in this step.

## Current Snapshot（2026-05-10）— V1.5-B1 Task Result History Service Foundation

- Purpose: Implement the task result history backend service per B0 design — new module, JSONL persistence, sanitization, and minimal integration into confirm_text_task.
- Key files: `src/xiaohuang/task_result_history_service.py` (new, ~180 lines), `tests/test_task_result_history_service.py` (new, 40 tests), `src/xiaohuang/control_panel_web_service.py` (+10 lines integration), `tests/test_control_panel_web_service.py` (+2 integration tests + 2 module boundary tests), `.gitignore` (+data/task_history/).
- Last completed:
  1. `task_result_history_service.py` — standalone module with `append_task_result()`, `get_recent_task_results()`, `sanitize_task_result_for_history()`, `init_task_history()`. Manages `data/task_history/task_results.jsonl` path. In-memory cache (max 100 entries). Never raises.
  2. Sanitization: `_redact_sensitive_text()` (api_key/token/password/secret/authorization/Bearer → <redacted>), `_compact_text()` (single-line + Traceback strip), `_truncate_text()` (title ≤100, summary ≤300, excerpt ≤500). Applied to all text fields before write.
  3. Save policy: only `status in ("completed", "failed")` AND `task_type in ALLOWED_READONLY_TASK_TYPES`. Returns None for blocked/cancelled/pending/expired/non-readonly.
  4. Schema: 16 fields (history_id, task_id, created_at, completed_at, task_type, title, status, ok, risk_level, summary, safe_details_excerpt, source, read_files_count, result_kind, tags, schema_version).
  5. Tags: all readonly → ["readonly"]; health → +"health"; logs/errors → +"logs"; config → +"config"; events → +"events"; diagnostic → +"diagnostic".
  6. Integration: `ControlPanelWebApi.confirm_text_task()` calls `append_task_result()` after task execution completes and registry is updated. Append failure is caught and silently records a runtime event warning — never affects the task result returned to the frontend.
  7. Module boundary enforced: `control_panel_web_service.py` does not open JSONL directly; `text_task_execution_service.py` does not contain `task_results.jsonl`; verified via static assertion tests.
- Verification: compileall OK; unittest discover OK (989 tests, 1 symlink-permission skip, +42 new); control_panel_web --help OK; voice_overlay --help OK; diff check OK.
- Known traps: `_reset_for_test()` must be called in setUp/tearDown for test isolation; inner try/except in confirm_text_task catches append failures silently; B1 is backend-only — no UI.

## Current Snapshot（2026-05-10）— V1.5-B0 Task Result History Design Doc

- Purpose: Design the task result history layer before any implementation. No code changes — design document only.
- Key files: `docs/task-result-history-design.md` (new), `TASK_MEMORY.md` (updated).
- Last completed:
  1. Design doc answers 10 core questions: why history, what to save, what NOT to save, where to save, schema fields, sanitization rules, differentiation from pending task registry and runtime events, extensibility, B1 minimum scope, and module boundaries.
  2. Recommended storage: local JSONL file (`data/task_history/task_results.jsonl`) + in-memory recent cache.
  3. Schema: 14 fields with `history_id`, `task_id`, timestamps, `task_type`, `status`, `summary`, `safe_details_excerpt` (≤500 chars, sanitized), `tags`, `schema_version`.
  4. Sanitization: unified redaction rules for api_key/token/password/secret/authorization/Bearer; Traceback → first line only; multi-line logs → statistics only; details → excerpt ≤500 chars.
  5. Module boundary mandate: `task_result_history_service.py` handles save/sanitize/read; `control_panel_web_service.py` only calls it after confirm; `text_task_execution_service.py` does NOT persist history.
  6. B1 scope: only completed/failed readonly task results; no chat messages, no pending/cancelled/blocked; no search/pagination/deletion; no database.
  7. Differentiation: pending task registry = "can execute" (short-lived, memory); runtime events = "what happened" (clearable, diagnostic); task history = "what I asked XiaoHuang to do and what the result was" (persistent, user-facing).
- Verification: git diff --check OK; git status clean (only docs/task-result-history-design.md + TASK_MEMORY.md changed).
- Known traps: B0 is design only — no code implementation; next step is V1.5-B1 implementation following this design.

## Current Snapshot（2026-05-10）— V1.5-A3.1 Health Report Error Signal Polish

- Purpose: Fix two issues — historical log errors should not be treated as current system broken, and technical PowerShell log lines should be summarized into human-readable diagnostics.
- Key files: `text_task_execution_service.py` (+`_summarize_log_signal`, revised classification, updated labels).
- Last completed:
  1. `_summarize_log_signal()` — recognizes ParserError/CategoryInfo/FullyQualifiedErrorId/AmpersandNotAllowed → human text; get_status failures; start/restart failures; fallback compact+redact.
  2. Classification: runtime events error → `health_errors`; path missing → `health_errors`; log error → `health_warnings` (was `health_errors`); log warning → `health_warnings`.
  3. Labels: 运行事件 shows "当前 error/warning" and "当前 error 提示"/"当前 warning 提示"; 日志 shows "历史 ERROR/WARNING" and section title "最近错误（历史日志）".
  4. Log extracts use `_summarize_log_signal` with dedup (`seen_signals`), max 2 representative signals, plus a "提醒" line.
  5. Summary: with only historical errors → "总体状态：有警告。历史日志中发现 N 条 ERROR 记录，建议排查来源。"
- Verification: compileall OK; unittest discover OK (945 tests, 1 symlink-permission skip, +3 new); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: Historical log errors alone never trigger "有错误"; ParserError/CategoryInfo never appear raw in report.

## Current Snapshot（2026-05-10）— V1.5-A3 Health Report Chat UX Polish

- Purpose: Optimize how the `readonly_health_report` result card renders in Chat — dedicated card with status badge, section parsing, clean typography.
- Key files: `app.js` (+4 helpers + branch), `style.css` (+~75 lines), tests (+3 static tests).
- Last completed:
  1. `renderHealthReportResultCard` — dedicated card when `task_type === readonly_health_report`, with head (title + status pill), summary, and parsed sections.
  2. `getHealthStatusFromResult` — parses "正常/有警告/有错误/信息不足" from summary+details.
  3. `getHealthStatusLabel` — maps `healthy/warning/error/unknown` to Chinese labels.
  4. `splitHealthReportSections` — splits details by `一、/二、/...` headers into `{title, body}` array.
  5. All text is `escapeHtml`'d; section body lines rendered as individual `<div>`s.
  6. CSS: `.health-report-card` (max-height 500px, scroll), `.health-state-pill` (4 color variants), `.health-report-section` layout.
  7. Generic `renderTextTaskExecutionResultCard` untouched for non-health tasks.
- Verification: compileall OK; unittest discover OK (942 tests, 1 symlink-permission skip, +3 new); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: No new actions on health card; section parser uses simple regex, falls back to `<pre>` if no sections found.

## Current Snapshot（2026-05-10）— V1.5-A2 Health Report Quality Polish

- Purpose: Quality improvements over A1 health report — better overall status tracking, config gap detection, compact runtime event excerpts, representative log error extracts, natural summary, overall status at top.
- Key files: `text_task_execution_service.py` (rewritten `_execute_readonly_health_report`, +`_compact_health_text`), tests.
- Last completed:
  1. Internal health tracking: `health_errors`, `health_warnings`, `health_unknowns` lists collected from all sub-modules; overall status derived from these.
  2. Config gaps: detects LLM/TTS disabled, empty voice/wake engine/display_name, reports as warnings with specific prompts.
  3. Runtime events: shows error/warning counts as `error/warning: 0/1` ratio; includes compacted last error and last warning excerpts (<=96 chars, Traceback stripped, redacted).
  4. Recent errors: extracts up to 3 representative log lines (compacted + redacted) instead of just a generic "found matches" note.
  5. Overall status at top of report (line 2), summary is natural Chinese sentence.
  6. `_compact_health_text()` helper: single-line, Traceback truncation, `_redact_sensitive_text` integration.
- Verification: compileall OK; unittest discover OK (939 tests, 1 symlink-permission skip, +5 new); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: config gap test needs all 6 paths present to avoid path-missing error overriding config warnings.

## Current Snapshot（2026-05-10）— V1.5-A1 Readonly Health Report Foundation

- Purpose: First "big feature" — aggregates existing D5 readonly capabilities (config, events, errors, paths) into one comprehensive health report task.
- Key files: `text_task_intent_service.py` (+18 keywords, detection after sub-tasks), `text_task_execution_service.py` (+`_check_basic_project_paths`, +`_execute_readonly_health_report`, whitelist), tests.
- Last completed:
  1. New `readonly_health_report` task type — low risk, requires confirmation, generates 6-section report.
  2. `_check_basic_project_paths()` checks 6 key paths (project_root, logs, scripts/control_panel_web.py, scripts/voice_overlay.py, src/xiaohuang, frontend/control_panel) — read-only, no create/repair.
  3. `_execute_readonly_health_report` aggregates: path check, config summary (with config_path), runtime events summary, recent errors summary (redacted), overall status (healthy/warning/error/unknown), and suggestions.
  4. Detection order: blocked > recent_errors > log_analysis > status_check > diagnostic > events > config > health_report
  5. Graceful degradation: sub-component failures show "X读取失败" but don't crash the whole report.
- Verification: compileall OK; unittest discover OK (934 tests, 1 symlink-permission skip, +7 new); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: health_report is last in detection to avoid over-matching; uses `config_path` from control panel; does NOT clear runtime events; does NOT write files.

## Current Snapshot（2026-05-10）— V1.5-UI0.7.1 Runtime Events Clear Polish

- Purpose: Three small fixes over UI0.7 — HTML-escape runtime event summary, don't record new event after clear, remove extra CSS `}`.
- Key files: `app.js` (escapeHtml), `control_panel_web_service.py` (no `_record_cp_event`), `style.css` (removed extra `}`).
- Last completed:
  1. `renderRuntimeEventEntries` now calls `escapeHtml(summary)` before injecting into HTML.
  2. `clear_runtime_events` no longer calls `_record_cp_event` — clearing leaves ring truly empty.
  3. Removed extra `}` after `#btn-clear-events` CSS block.
  4. Test `test_clear_runtime_events_removes_events` now asserts `get_recent_events(20) == []`; new frontend static test `test_js_runtime_event_summary_is_escape_htmled`.
- Verification: compileall OK; unittest discover OK (927 tests, 1 symlink-permission skip); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: None — clearing now truly empties the ring.

## Current Snapshot（2026-05-10）— V1.5-UI0.7 Runtime Events Display Hygiene and Clear Recent Events

- Purpose: Fix runtime events display (too noisy with full tracebacks) and add one-click clear button.
- Key files: `runtime_events/service.py` (+`clear_recent_events()`), `control_panel_web_service.py` (+`clear_runtime_events` API), `frontend/*` (compact text + clear button).
- Last completed:
  1. `clear_recent_events()` public function in runtime_events service — clears in-memory ring, returns count removed. Does NOT touch files.
  2. `ControlPanelWebApi.clear_runtime_events()` API — calls `clear_recent_events()`, records a runtime event for the action, returns `{ok, data: {removed}}`.
  3. Frontend `compactRuntimeEventText()` truncates at 110 chars and strips Traceback suffix; `renderRuntimeEvents` renders to both Diagnostics page and Home drawer with summary-only display.
  4. "清空事件" button on Diagnostics page in the 运行事件 card, with loading state and success/failure toast.
  5. CSS max-height (280px) and `overflow-y:auto` on events lists; single-line `text-overflow:ellipsis` on entries.
- Verification: compileall OK; unittest discover OK (926 tests, 1 symlink-permission skip); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: `clear_runtime_events` records its own event (one event remains after clear); constructor's `init_event_logger` may load from disk JSONL.

## Current Snapshot（2026-05-10）— V1.5-UI0.5 Chat Focus Mode Remove Redundant Header Chrome

- Purpose: Put Chat into focus mode by removing the two remaining top chrome layers only on the Chat page.
- Key files: `frontend/control_panel/assets/style.css`, `tests/test_control_panel_web_service.py`.
- Last completed:
  1. Added `body.chat-page .topbar{display:none!important}` so the global command bar is hidden only in Chat.
  2. Added Chat-specific app-shell grid overrides so no topbar row/blank space remains, including sidebar-collapsed combinations.
  3. Added `body.chat-page #section-chat .text-chat-header{display:none!important}` so the “对话 / 说明 / 本地文本入口” row is hidden in focus mode.
  4. Kept Chat message surface, right session rail, composer, internal scroll, sidebar collapse, and non-home drawer hiding intact.
- Verification: compileall OK; unittest discover OK (917 tests, 1 symlink-permission skip); control_panel_web `--help` OK; voice_overlay `--help` OK; pywebview startup smoke stayed alive for 6s; diff check OK; targeted `V13UIFrontendStructureTests` OK (38 tests).
- Known traps: Topbar must remain present in HTML and visible outside Chat; focus mode is CSS-scoped to `body.chat-page`.

## Current Snapshot（2026-05-10）— V1.5-UI0.4 Minimal Spacious Chat Surface Polish

- Purpose: Reduce stacked chrome and make Chat feel quieter, lighter, and more spacious without changing behavior.
- Key files: `frontend/control_panel/index.html`, `frontend/control_panel/assets/app.js`, `frontend/control_panel/assets/style.css`, `tests/test_control_panel_web_service.py`.
- Last completed:
  1. Chat header copy shortened and CSS compressed the header to a compact inline surface with a smaller status chip.
  2. Topbar chrome was thinned: smaller logo, tighter chips/buttons, lighter shadow/border, calmer command-bar feel.
  3. Welcome message shortened; first assistant bubble is styled as a soft system message instead of a heavy banner.
  4. Composer and prompt chips were tightened; the model pill is hidden on Chat to reduce repeated metadata; right session rail is lighter and remains present.
- Verification: compileall OK; unittest discover OK (916 tests, 1 symlink-permission skip); control_panel_web `--help` OK; voice_overlay `--help` OK; pywebview startup smoke stayed alive for 6s; diff check OK; targeted `V13UIFrontendStructureTests` OK (37 tests).
- Known traps: Keep Chat internal scrolling, sidebar collapse, non-home drawer hiding, and right-side session rail intact; this is visual weight reduction only.

## Current Snapshot（2026-05-10）— V1.5-UI0.3 Chat Right Utility Rail and Collapsible Sidebar

- Purpose: Move Chat's session helper rail to the right side and add persistent collapsible primary sidebar for more workspace room.
- Key files: `frontend/control_panel/index.html`, `frontend/control_panel/assets/app.js`, `frontend/control_panel/assets/style.css`, `tests/test_control_panel_web_service.py`.
- Last completed:
  1. Chat DOM/layout now places `text-chat-main` before `text-chat-sessions`, with grid `messages + right session rail` (`minmax(0,1fr) minmax(250px,300px)`).
  2. Added sidebar toggle button (`btn-sidebar-toggle`) and icon/text nav items with titles for collapsed hover context.
  3. Added `SIDEBAR_STORAGE_KEY`, `initSidebarControls()`, and `sidebar-collapsed` body state persisted in localStorage.
  4. CSS covers expanded/collapsed sidebar grids for Home, Home with collapsed drawer rail, and non-home pages; Chat internal scroll and non-home drawer hiding remain intact.
- Verification: compileall OK; unittest discover OK (915 tests, 1 symlink-permission skip; one ResourceWarning printed but tests passed); control_panel_web `--help` OK; voice_overlay `--help` OK; pywebview startup smoke stayed alive for 6s; diff check OK; targeted `V13UIFrontendStructureTests` OK (36 tests).
- Known traps: DOM order matters for right-side Chat sessions; collapsed sidebar grid rules must remain compatible with `non-home-page` and `drawer-collapsed`.

## Current Snapshot（2026-05-10）— V1.5-UI0.2 Chat Scroll Container and Non-Home Drawer Cleanup

- Purpose: Fix follow-up App Shell acceptance issues — no non-home diagnostic rail residue, and Chat messages must scroll inside the chat card instead of growing the window.
- Key files: `frontend/control_panel/assets/app.js`, `frontend/control_panel/assets/style.css`, `tests/test_control_panel_web_service.py`.
- Last completed:
  1. `updateShellLayoutForSection()` now also toggles `home-page`, `non-home-page`, and `chat-page` while keeping previous `drawer-page` / `no-drawer-page` compatibility.
  2. Non-home CSS hides diagnostic drawer, rail, and any drawer toggle, including the collapsed rail override path.
  3. Chat page has fixed-height section rules (`height:100%`, `min-height:0`) and `body.chat-page .main-workspace{overflow:hidden}` so messages cannot stretch the whole page.
  4. Chat message list has internal `overflow-y:auto`, `overscroll-behavior:contain`, and `scrollTextChatToBottom()` is used after rendering.
- Verification: compileall OK; unittest discover OK (914 tests, 1 symlink-permission skip); control_panel_web `--help` OK; voice_overlay `--help` OK; pywebview startup smoke stayed alive for 6s; diff check OK; targeted `V13UIFrontendStructureTests` OK (35 tests).
- Known traps: The generic `.app-shell.drawer-collapsed .drawer-rail{display:flex}` rule must stay overridden for non-home pages; do not remove `min-height:0` from chat ancestors.

## Current Snapshot（2026-05-10）— V1.5-UI0.1 Context Panel Scope and Chat Space Polish

- Purpose: Fix the first App Shell layout issue where the right diagnostic context panel crowded every page, especially Chat.
- Key files: `frontend/control_panel/index.html`, `frontend/control_panel/assets/app.js`, `frontend/control_panel/assets/style.css`, `tests/test_control_panel_web_service.py`.
- Last completed:
  1. Added `updateShellLayoutForSection()` so `home` gets `drawer-page`; all other primary pages get `no-drawer-page`.
  2. CSS now removes the right diagnostic drawer/rail from non-home pages and expands the shell to sidebar + main workspace without leaving blank space.
  3. Top “诊断” button is now a Diagnostics page entry (`open-diagnostics`) instead of a drawer collapse control; Home still keeps drawer collapse/rail controls.
  4. Chat layout is two columns (`sessions + messages`) and the right `text-chat-workspace` column is hidden to give message/composer space back.
- Verification: compileall OK; unittest discover OK after one unrelated flaky diagnostic-export filename collision was rerun cleanly (913 tests, 1 symlink-permission skip); control_panel_web `--help` OK; voice_overlay `--help` OK; pywebview startup smoke stayed alive for 6s; diff check OK; targeted `V13UIFrontendStructureTests` OK (34 tests).
- Known traps: Keep the drawer localStorage collapse behavior only for Home; do not re-add a global right drawer to Chat/Tasks/Tools/Diagnostics/Settings.

## Current Snapshot（2026-05-10）— V1.5-UI0 App Shell Layout Foundation

- Purpose: Reframe the control panel frontend as a durable App Shell with Top Bar / fixed primary Sidebar / Main Workspace / right Context Panel.
- Key files: `frontend/control_panel/index.html`, `frontend/control_panel/assets/app.js`, `frontend/control_panel/assets/style.css`, `tests/test_control_panel_web_service.py`.
- Last completed:
  1. Sidebar now exposes only six primary pages: 首页 / 对话 / 任务 / 工具 / 诊断 / 设置.
  2. Chat is a normal primary workspace page (`section-chat`), not a separate full-window `text-chat-shell`; top “文本对话” remains as a shortcut into the same Chat page via `switchShell('text-chat')`.
  3. Home keeps runtime cards and quick actions; Settings contains wake/voice controls and wake detail rows; Diagnostics keeps event/export affordances; Tasks/Tools are safe placeholders only.
  4. Frontend feedback tightened with button active/focus/loading states and capped toast stacking.
- Verification: compileall OK; unittest discover OK (910 tests, 1 symlink-permission skip); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK; targeted `V13UIFrontendStructureTests` OK (31 tests).
- Known traps: Do not reintroduce old sidebar categories as primary nav; `switchSection()` keeps aliases for old section ids so legacy JS calls land on the new pages; no backend/API/text interaction service changes were made.

## Current Snapshot（2026-05-09）— V1.4-D5.1 Readonly Review Safety Fixes

- Purpose: Fix two D5 issues — real sensitive field redaction in log details, and config_path propagation from control panel to config summary.
- Key files: `text_task_execution_service.py`, `control_panel_web_service.py`, tests.
- Last completed:
  1. Added `_redact_sensitive_text()` helper with 3 regex patterns covering: `api_key=xxx`, `token=xxx`, `password=xxx`, `secret=xxx`, `authorization=xxx`, `Bearer xxx` (case-insensitive). Applied BEFORE truncation in `_analyze_recent_logs()` detail_lines.
  2. Added optional `config_path` parameter to `execute_confirmed_text_task()` and `_execute_readonly_config_summary()`; `control_panel_web_service.confirm_text_task` now passes `self._resolve_config_path()`.
  3. Fixed old redaction test to use log lines containing error/warning/failed keywords (so they actually get sampled into detail_lines), proving redaction works. Tests use: `ERROR api_key=sk-..., WARNING token=abc123, FAILED password=..., etc.`
  4. Added config_path execution test (temp custom config) + ControlPanel API-level test (ControlPanelWebApi passes config_path through).
- Verification: compileall OK; unittest discover OK (909 tests, 1 symlink-permission skip, +3 new); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: None config_path uses default config; redaction is regex-based, covers common formats but not exhaustive; don't add new task types or keywords.

## Current Snapshot（2026-05-09）— V1.4-D5 More Readonly Task Types

- Purpose: Add 3 new safe readonly task types — recent errors review, runtime events review, and config summary — extending the existing confirm → execute → result card pipeline.
- Key files: `text_task_intent_service.py` (new term sets), `text_task_execution_service.py` (3 new handlers + whitelist), `tests/` (intent + execution + control panel API tests).
- Last completed:
  1. `readonly_recent_errors_review` — keyword detection (最近错误/报错/异常 etc.), reads logs safety (reuses existing helpers), redacts sensitive values, handles empty logs directory gracefully
  2. `readonly_runtime_events_review` — keyword detection (最近事件/运行事件/运行记录 etc.), calls `get_recent_events()`, aggregates by source/type, counts errors/warnings, handles empty events gracefully, does NOT clear ring buffer
  3. `readonly_config_summary` — keyword detection (当前配置/配置摘要 etc.), calls `load_config()`, outputs human-readable summary (LLM/TTS/wake/STT/conversation/overlay/runtime), shows env var name (not value), no API keys/secrets/passwords
  4. All 3 types follow the existing pipeline: intent → pending_task → registry → confirm (task_id only) → execute → result card
- Detection order: blocked_local_execution > recent_errors_review > log_analysis > status_check > diagnostic_review > runtime_events_review > config_summary
- Verification: compileall OK; unittest discover OK (906 tests, 1 symlink-permission skip, +13 new); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: _RECENT_ERRORS_TERMS before _LOG_TERMS in detection order (overlap on "报错"); config summary reads default config in tests (no user config); events review reads from memory ring.

## Current Snapshot（2026-05-09）— V1.4-Q3.1 Capability Router Risk Pattern Normalization Hardening

- Purpose: Fix high-risk pattern matching — patterns with spaces ("rm -", "del ", "format ") were not matching normalized user input, causing dangerous requests to potentially bypass the deny check. Now all pattern matching uses the same `_normalize_command_text` helper.
- Key files: `src/xiaohuang/capabilities/local_commands/service.py`, `tests/test_capability_router.py`.
- Last completed:
  1. Added `_normalize_command_text()` helper: `str(text or "").replace(" ", "").lower()`
  2. Applied to all three matching loops: high-risk patterns, whitelist keywords, denied keywords — all normalize both the input AND the pattern/keyword
  3. Whitelist matching now records the actual matched keyword (not just `keywords[0]`)
  4. 7 new tests: rm/del/format space patterns properly denied, whitelist regression, high-risk priority over whitelist, normal chat regression
- Behavior: "rm -rf", "del file.txt", "format c:" (and case/spacing variants) now correctly detected as `not_allowed`; all existing whitelist keywords still work; high-risk check still takes priority over whitelist; normal chat unaffected.
- Verification: compileall OK; unittest discover OK (893 tests, 1 symlink-permission skip, +7 new); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: do not add new keywords or patterns; this is normalization hardening only.

## Current Snapshot（2026-05-09）— V1.4-Q3 Capability Router Test Coverage

- Purpose: Extend capability router test coverage — normalization, route/execute separation, disabled capability, risk labels, refusal messages, and runtime event recording.
- Key files: `tests/test_capability_router.py` (extended, +15 tests, now 51 total).
- Last completed: 7 new test classes:
  - `RouteCapabilityNormalizationTests` (5) — whitespace trimming, internal spaces, case folding with Chinese-English mix, whitespace-only not_task
  - `RouteVsExecuteSeparationTests` (1) — `route_capability` does NOT call capability handlers, only returns decisions
  - `DisabledCapabilityTests` (1) — disabled cap routes as `capability_disabled` with its name in message
  - `CapabilityRiskLabelTests` (2) — all 5 core caps are `low` risk + have all required fields
  - `RefusalMessageContentTests` (2) — high-risk and denied keyword messages contain "白名单"
  - `CapabilityRuntimeEventsTests` (2) — successful execution records `capability_invoked` + `capability_completed`; handler exception records `capability_failed`
  - `NotTaskEdgeCaseTests` (2) — chat-like texts are not_task; keyword embedded in sentence still detected
- Key observations: normalization only removes spaces and lowercases input text, does NOT normalize keyword strings; pure English "OPEN LOGS" won't match Chinese-containing keywords; keywords with internal spaces (like "rm -") won't match normalized input because spaces are stripped from input but not keywords.
- Verification: compileall OK; unittest discover OK (886 tests, 1 symlink-permission skip, +15 new); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: do not add new keywords or capabilities; do not change normalization logic; route_capability is pure decision, not execution.

## Current Snapshot（2026-05-09）— V1.4-Q2 Runtime Events Test Coverage

- Purpose: Extend runtime events test coverage — blank/empty edge cases, leveled events, details JSON-friendliness, ControlPanelWebApi exposure, and capability router event recording.
- Key files: `tests/test_runtime_events_service.py` (extended, +17 tests, now 38 total).
- Last completed: 5 new test classes:
  - `LevelPreservationTests` (4) — info/warning/error/default level preserved
  - `BlankSourceOrTypeTests` (3) — empty string source/event_type/message accepted as-is
  - `DetailsEdgeCaseTests` (5) — None/empty dict details, JSON-friendly complex dicts, nested sensitive field filtering
  - `ControlPanelRuntimeEventsApiTests` (2) — `get_runtime_events()` returns ok with events, response is JSON-serializable
  - `CapabilityEventRecordingTests` (2) — `get_status` and `export_diagnostics` capabilities record `capability_router` events
- Key observations: `get_recent_events` returns oldest-first (FIFO), not newest-first; there is no public `clear_events` function; empty strings are stored as-is; system unchanged.
- Verification: compileall OK; unittest discover OK (871 tests, 1 symlink-permission skip, +17 new); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: no clear/reset API — use `svc._ring.clear()` for test isolation; ring buffer max 200, limit clamped to [1,100]; empty strings for source/type are stored as empty strings, not "unknown".

## Current Snapshot（2026-05-09）— V1.4-Q1 App Config Service Test Coverage

- Purpose: Dedicated test suite for `app_config_service.py` — lock down config loading, merging, coercion, CLI override, and frozen dataclass behavior.
- Key files: `tests/test_app_config_service.py` (new, 41 tests).
- Last completed: 5 test classes covering default config, load_config (missing/invalid/non-object/valid), merge_config_dict (non-object section skip), wake phrases/aliases (string/list/empty/invalid), numeric out-of-range fallback, bool coercion (type-strict), assistant overrides, LLM/TTS/overlay field merge, apply_cli_overrides (scalar values, store_true semantics, None passthrough, CLI True overrides config False), and frozen dataclass behavior.
- Behavior: all existing app_config_service functions unchanged; tests verify current behavior as-is.
- Verification: compileall OK; unittest discover OK (854 tests, 1 symlink-permission skip, +41 new); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: `_coerce_bool` accepts only `bool` type, not strings; `_or_config` False means "not passed"; list fields inside frozen dataclass are still mutable in-place.

## Current Snapshot（2026-05-09）— V1.4-D4.1 Registry Edge Hardening / UX Polish

- Purpose: Small security and UX patch over D4 — prevent tasks stuck in executing, friendly blocked reason text, natural expiry label.
- Key files: `control_panel_web_service.py`, `frontend/control_panel/assets/app.js`, `tests/test_control_panel_web_service.py`.
- Last completed:
  1. `confirm_text_task` wraps execution in inner try/except; unexpected exceptions after claim now call `mark_failed` and return `_registry_failed_result` instead of leaving task stuck in `executing`.
  2. `_registry_reason_text` maps 7 internal reason codes to friendly Chinese summary/details; `_registry_blocked_result` calls it; `error` field still preserves raw reason code.
  3. Frontend `formatTaskExpiryLabel` computes remaining time from `expires_at` / `expires_in_seconds` and shows "约 N 分钟内有效" (or "N 秒内有效" for < 60s), replacing the old raw seconds inline format.
- Behavior: normal completed/blocked/failed result flow unchanged; normal task execution not affected by the new try/except; frontend still sends only `task_id`.
- Verification: compileall OK; unittest discover OK (813 tests, 1 symlink-permission skip); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: keep this as edge hardening only; do not add new task types, execution capabilities, or modify `text_task_execution_service.py`.

## Current Snapshot（2026-05-09）— V1.4-D4 Pending Task Registry / Server-side Task Store

- Purpose: Pending text tasks are stored server-side; confirmation now trusts only registry task IDs, not frontend task payloads.
- Key files: `text_task_registry_models.py`, `text_task_registry_service.py`, `control_panel_web_service.py`, `frontend/control_panel/assets/app.js`.
- Last completed: added in-memory registry with TTL/capacity/status transitions, registered pending tasks on `send_text_message`, changed confirm to `task_id`, and added `cancel_text_task`.
- Behavior: unknown, expired, repeated, cancelled, or forged pending task confirmations return blocked registry-compatible result cards.
- Verification: compileall OK; unittest discover OK (803 tests, 1 symlink-permission skip); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: keep registry in memory only; do not add persistence, new task types, generic execution, `local_commands`, or database access.

## Current Snapshot（2026-05-09）— V1.4-D3.1 Readonly Task Result Card UI

- Purpose: Render confirmed readonly task execution results as structured cards instead of plain assistant text.
- Key files: `frontend/control_panel/assets/app.js`, `frontend/control_panel/assets/style.css`, `tests/test_control_panel_web_service.py`.
- Last completed: execution result messages now carry `executionResult`, render completed/blocked/failed cards, and show summary, details, read files, and error code.
- Behavior: `confirm_text_task` call and pending task card logic stay unchanged; result display is frontend-only.
- Verification: compileall OK; unittest discover OK (789 tests, 1 symlink-permission skip); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: do not modify backend execution, task types, `confirm_text_task`, or any local command capability from this UI task.

## Current Snapshot（2026-05-09）— V1.4-D3.0.1 Log Symlink Safety Hardening

- Purpose: Harden readonly log selection so confirmed text tasks cannot follow log symlinks outside `logs/`.
- Key files: `text_task_execution_service.py`, `tests/test_text_task_execution_service.py`.
- Last completed: `_recent_log_files()` now skips symlinks, checks resolved path containment under `logs/`, isolates per-file errors, and uses safe mtime sorting.
- Behavior: normal `.log` and `.txt` files under `logs/` are still read; symlinked log files are skipped.
- Verification: compileall OK; unittest discover OK (787 tests, 1 symlink-permission skip); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: keep this as log selection hardening only; do not change frontend, ControlPanel API, task types, or execution capability.

## Current Snapshot（2026-05-09）— V1.4-D3 Confirmed Readonly Task Execution

- Purpose: Confirmed text task cards can now call a backend API that executes only whitelisted readonly tasks.
- Key files: `text_task_execution_models.py`, `text_task_execution_service.py`, `control_panel_web_service.py`, `frontend/control_panel/assets/app.js`.
- Last completed: added `confirm_text_task`, readonly log/status/diagnostic execution, backend re-validation, and frontend executing/completed/blocked/failed states.
- Behavior: only `readonly_log_analysis`, `readonly_status_check`, and `readonly_diagnostic_review` can run; blocked/high-risk/unknown tasks return structured blocked results.
- Verification: compileall OK; unittest discover OK (785 tests); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: do not add generic `execute_text_task`, do not call `local_commands`, subprocess, PowerShell, cmd, or write/export diagnostics from this path.

## Current Snapshot（2026-05-09）— V1.4-D1.1.1 Text Task Card Field Mapping Fix

- Purpose: Align the text task confirmation card with the D1 backend field names.
- Key files: `frontend/control_panel/assets/app.js`, `frontend/control_panel/assets/style.css`, `tests/test_control_panel_web_service.py`.
- Last completed: card risk now prefers `pending_task.risk_level` before `risk`, clamps unknown risks to medium, and shows optional `original_text` as “原始输入”.
- Behavior: confirm/cancel still only update frontend state and append local assistant feedback; no backend execution path was added.
- Verification: compileall OK; unittest discover OK after rerun (773 tests; first run hit existing diagnostic export timestamp collision); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: keep this as UI-only mapping; do not connect card actions to task execution or `local_commands`.

## Current Snapshot（2026-05-09）— V1.4-D1.1 Text Task Confirmation Card UI

- Purpose: Text chat renders backend `pending_task` responses as an in-window confirmation card without executing the task.
- Key files: `frontend/control_panel/assets/app.js`, `frontend/control_panel/assets/style.css`, `tests/test_control_panel_web_service.py`.
- Last completed: pending tasks now show title, summary, risk, status, and local confirm/cancel controls inside the full-window text chat.
- Behavior: confirm/cancel only updates frontend message state and appends a local assistant note; no new backend API or command execution path is added.
- Verification: compileall OK; unittest discover OK (773 tests); control_panel_web `--help` OK; voice_overlay `--help` OK; diff check OK.
- Known traps: do not wire card buttons to task execution until the confirmed readonly execution contract exists; avoid `local_commands` from frontend code.

## Current Snapshot（2026-05-09）— V1.4-D1 Text Task Confirmation Backend Contract

- Purpose: Text chat can detect local task intent and return a structured `pending_task` that requires confirmation, without executing anything.
- Key files: `text_task_models.py`, `text_task_intent_service.py`, `text_task_confirmation_service.py`, `text_interaction_models.py`, `text_interaction_service.py`.
- Last completed: deterministic intent detection for readonly log/status/diagnostic review and blocked local execution.
- Behavior: panel command guard still wins; task intents return `requires_confirmation=True`, `reply_source=pending_task`, and no reply runtime call.
- Verification: compileall OK; unittest discover OK (771 tests); control_panel_web `--help` OK; diff check OK.
- Known traps: D1 is contract only; do not call `local_commands.execute_capability`, write DB/files, or add frontend confirmation UI here.
- Next likely edit points: V1.4-D2 frontend confirmation card UI, V1.4-D3 confirmed readonly execution.

## Current Snapshot（2026-05-09）— V1.4-C.3 Remove Text Chat From Control Sidebar

- Purpose: Keep text chat as a full-window mode entered only from the top control button, not a sidebar category.
- Key files: `frontend/control_panel/index.html`, `tests/test_control_panel_web_service.py`.
- Last completed: removed `data-section="text-chat"` from the control sidebar; top `data-action="open-text-chat"` still switches to `text-chat-shell`.
- Verification: compileall OK; unittest discover OK (759 tests); control_panel_web `--help` OK; diff check OK.
- Known traps: do not re-add text chat to the control navigation; frontend must not call `open_text_chat_window`.

## Current Snapshot（2026-05-09）— V1.4-C.2 Fullscreen Text Chat Mode

- Purpose: Make text chat a full-window mode inside the same pywebview app, not a module inside control center.
- Key files: `frontend/control_panel/index.html`, `frontend/control_panel/assets/app.js`, `frontend/control_panel/assets/style.css`, `tests/test_control_panel_web_service.py`.
- Last completed: `control-shell` and `text-chat-shell` are top-level siblings; text mode hides control nav/topbar/diagnostic drawer.
- Behavior: top button and left nav switch to `text-chat-shell`; `btn-back-control` returns to control shell.
- Verification: compileall OK; unittest discover OK (759 tests after rerun); control_panel/voice_overlay/text_chat `--help` OK; diff check OK.
- Known traps: frontend must not call `open_text_chat_window`; keep using `send_text_message` / `clear_text_session`.
- Next likely edit points: visual click-through QA in pywebview, legacy standalone removal, task confirmation flow.

## Current Snapshot（2026-05-09）— V1.4-C.1 Single Shell UI

- Purpose: Merge control center and text chat into one pywebview control panel window.
- Key files: `frontend/control_panel/index.html`, `frontend/control_panel/assets/app.js`, `frontend/control_panel/assets/style.css`, `src/xiaohuang/control_panel_web_service.py`.
- Startup/test: `F:\for_xiaohuang\conda310\python.exe scripts\control_panel_web.py`; text chat is selected inside the same shell.
- Last completed: left nav/top button switch to `section-text-chat`; ControlPanelWebApi exposes `send_text_message` and `clear_text_session`.
- Verification: compileall OK; unittest discover OK (759 tests); control_panel/voice_overlay/text_chat `--help` OK; same-window API smoke OK.
- Known traps: `open_text_chat_window` intentionally returns `{same_window: True}` and must not launch `scripts/text_chat_web.py`.
- Next likely edit points: remove legacy standalone text chat after manual acceptance, add temporary multi-session list, add text task confirmation.

## Current Snapshot（2026-05-09）— V1.4-C Standalone Text Chat Window

- Purpose: Add a second user entry for typed XiaoHuang conversations without touching voice/STT/TTS startup.
- Key files: `scripts/text_chat_web.py`, `frontend/text_chat/*`, `src/xiaohuang/text_interaction_*`, `src/xiaohuang/text_chat_web_service.py`, control panel open button/API.
- Startup/test: `F:\for_xiaohuang\conda310\python.exe scripts\text_chat_web.py`; control panel opens it through `open_text_chat_window`.
- Behavior: in-process short-term `ConversationMemory` only; no database, no long-term chat files, no mic/STT/openWakeWord/TTS.
- Guard: panel control phrases return `reply_source=panel_command_guard` and `blocked_panel_command=True`.
- Verification: compileall OK; unittest discover OK; text_chat/control_panel/voice_overlay `--help` OK; guard smoke OK.
- Known traps: text entry deliberately bypasses capability execution by using a text-only reply pipeline function.
- Next likely edit points: temporary multi-session UI, text task confirmation flow, shared voice/text task routing.

## Current Snapshot（2026-05-06）— V1.3 PySide6 Voice Dock + Configurable CUDA STT

- 当前阶段：V1.3 PySide6 transparent voice dock + configurable CUDA STT
- Voice overlay 最终方案：PySide6 / QWidget / QPainter
- 不再使用 pywebview HTML voice overlay
- 不再使用 Tkinter Canvas / Pillow waveform 作为最终方案
- 控制面板：pywebview Web Control Panel，frontend/control_panel/*
- wake engine：openwakeword
- wake phrase：hey jarvis
- STT：FunASR SenseVoiceSmall，常驻 stt_server.py
- STT device：支持 cpu / cuda:0，默认 cpu
- GPU 环境：torch 2.10.0+cu126，torchaudio 2.10.0+cu126，RTX 4050 Laptop GPU
- /health 已验证 stt_device=cuda:0、model_loaded=True、status=ready
- LLM：DeepSeek API，日志中 source=llm
- TTS：edge-tts 在线合成

### 验证结果（2026-05-06）

- compileall OK
- unittest discover OK：615 tests OK
- scripts\stt_server.py --help OK
- PySide6 overlay 人工验收 OK
- CUDA STT 人工验收 OK
- nvidia-smi 可见 Python 占用 GPU 显存（约 1.7GB）
- voice_overlay 日志出现 openwakeword_wake_event / command_record_start / Overlay command transcription / Overlay reply source=llm

### V1.3C-A Startup Failure Diagnostics（2026-05-07）

- 新增 `capabilities/startup_diagnostics/` — 独立 capability 目录
- `startup_diagnostics/service.py`：读取日志尾部，识别 5 类常见启动失败原因
- 能识别：内存不足/模型加载失败、run_env.ps1 解析错误、端口占用/health 不可达、模型缓存/下载异常、未知错误
- 启动/重启失败时自动调用诊断，结果附加到 API response 的 `diagnostic` 字段
- 前端 `drawer-last-error` 展示诊断摘要、建议和日志来源
- Runtime Event 记录 `control_panel/startup_diagnostic` 事件
- 诊断导出 TXT 新增"八、启动失败诊断" section
- 未修改 voice overlay / wake / STT / LLM / TTS 主链路
- 新增 `tests/test_startup_diagnostics_service.py`（28 tests）

### V1.3C-B Preflight Check（2026-05-07）

- 新增 `capabilities/preflight_check/` — 独立 capability 目录
- `preflight_check/service.py`：启动前资源检查，含 5 个检查项
- 检查项：物理内存/虚拟内存（threshold ok≥6GB/warn≥3GB）、STT 端口 8766、Python 环境、模型缓存（SenseVoiceSmall + VAD model.pt）、logs 目录可写性
- 控制面板右侧诊断栏新增"启动前检查"按钮和结果展示区
- 检查结果按 ok/warning/error 分级，含人话摘要和建议
- Web API `get_preflight_check()` 返回结构化 PreflightCheckResult
- Runtime Event 记录 `control_panel/preflight_check` 事件
- 诊断导出 TXT 新增"九、启动前检查" section
- 未修改 voice overlay / wake / STT / LLM / TTS 主链路
- 新增 `tests/test_preflight_check_service.py`（25 tests）

### V1.4-A Capability Router MVP（2026-05-07）

- 新增 `capabilities/local_commands/` — 安全白名单能力路由层
- `local_commands/models.py`：RouteDecision / LocalCommandIntent / LocalCommandResult / CapabilityDefinition
- `local_commands/registry.py`：5 个白名单能力 + lazy handler
- `local_commands/service.py`：中文关键词确定性匹配（不用 LLM function calling）+ 执行分发
- 5 个安全白名单能力：open_logs_folder / run_preflight_check / get_status / export_diagnostics / open_control_panel
- 安全边界：危险关键词（powershell/cmd/shell/shutdown/微信/Q等）优先拒绝，fail closed
- 接入 reply_pipeline_service：可执行能力直接返回结果不调 LLM，不可执行能力返回明确拒绝
- 保留旧 task_router_service 兼容接口
- Runtime Event 记录 capability_invoked/completed/failed 事件
- 未修改 voice overlay / wake / STT / LLM / TTS 主链路
- 新增 `tests/test_capability_router.py`（36 tests）

### V1.3B-D Open Logs Folder（2026-05-06）

- Web 控制面板新增"打开日志目录"按钮，点击后用系统资源管理器打开项目 `logs/` 目录
- `control_panel_web_service.py` 新增 `open_logs_folder()` 薄 API
- 后端只打开项目内 `logs` 目录，不接受前端传入路径
- Runtime Event 记录 `control_panel/open_logs_folder` 事件
- 未修改 voice overlay / wake / STT / LLM / TTS 主链路

### V1.3B-C Runtime Event Stream（2026-05-06）

- 新增 `capabilities/runtime_events/` — 独立 capability 目录
- `runtime_events/service.py`：内存 ring buffer + JSONL 追加写入 + `record_event()` / `get_recent_events()`
- 事件写入 `logs/runtime_events.jsonl`，重启后可从磁盘恢复最近事件
- Web 控制面板右侧新增"运行事件"区块，刷新状态时自动加载
- 诊断导出 TXT 追加"七、运行事件" section
- 接入点：`control_panel_web_service`（start/stop/restart/export）、`stt_server.py`（server ready）、`voice_overlay.py`（worker started）
- 未深度侵入 openWakeWord / STT / LLM / TTS 语音主链路
- 敏感字段自动过滤，写入失败不抛致命异常
- 新增 `tests/test_runtime_events_service.py`（21 tests）

### V1.3B-B Diagnostic Export TXT（2026-05-06）

- 新增 `capabilities/diagnostic_export/` — 独立 capability 目录
- `diagnostic_export/service.py`：`format_diagnostics_text()` + `export_diagnostics_to_file()`
- Web 控制面板右侧诊断栏新增"导出 TXT"按钮
- 导出文件写入 `logs/diagnostic_exports/xiaohuang_diagnostics_YYYYMMDD_HHMMSS_micros.txt`
- `control_panel_web_service.py` 新增 `export_diagnostics_text()` 薄 API 方法
- 敏感字段（api_key, secret, password, token, etc.）自动过滤，不进入导出文本
- HTML 特殊字符转义，路径限制在 `logs/diagnostic_exports/` 内
- 未修改 voice overlay / wake / STT / LLM / TTS 主链路
- 新增 `tests/test_diagnostic_export_service.py`（24 tests）

### V1.3A voice_overlay bootstrap extraction（2026-05-06）

- 新增 `src/xiaohuang/voice_overlay_bootstrap_service.py`（~160 行）：`VoiceOverlayBootstrapResult` dataclass + `bootstrap_voice_overlay()` 函数
- `scripts/voice_overlay.py` 从 414 行缩减到 358 行（-56 行），配置装配逻辑迁移至 bootstrap service
- 新增 `tests/test_voice_overlay_bootstrap_service.py`（23 tests）
- 本次未修改 PySide6 UI 外观
- 未修改 openWakeWord / STT / LLM / TTS 主链路
- `legacy_config`（YAML 项目默认配置）与 `app_config`（JSON 用户配置）暂时并存，命名明确
- bootstrap service 只负责"加载配置 + 组装 options/config"，不做 UI、不做线程、不做网络

---

## RTK onboarding snapshot（2026-05-06）

- Purpose: Windows 桌面语音助手；当前真实代码已超过 README 的 V1.2E，处在 V1.3 UI / overlay dock 与 Web 控制面板迭代后状态。
- Key entry points: `scripts/voice_overlay.py`（PySide6 透明音波 dock + runtime 组装）、`scripts/stt_server.py`、`scripts/control_panel.py`、`scripts/control_panel_web.py`、`scripts/tray_app.py`。
- Runtime boundaries: `voice_overlay.py` 不再承载主循环业务；主循环在 `overlay_loop_runtime_service.py`，wake 在 `wake_runtime_service.py` / `openwakeword_adapter.py`，command 在 `command_runtime_service.py`，reply/session 在 `reply_runtime_service.py` / `assistant_runtime_service.py`。
- UI surfaces: Tk 控制面板仍在 `scripts/control_panel.py`；pywebview 控制面板通过 `control_panel_web_service.py` + `frontend/control_panel/*`；voice overlay 已替换为 `voice_overlay_qt_ui.py` 的 PySide6 透明音波 dock，旧 `frontend/voice_overlay/*` 原型资产已删除。
- Startup/test: 先 dot-source `.\scripts\run_env.ps1`；Python 固定用 `F:\for_xiaohuang\conda310\python.exe`。
- Baseline verification on 2026-05-06: `unittest discover -s tests -q` 535 tests OK；`compileall -q src scripts tests` OK；`scripts\voice_overlay.py --help` OK。
- Git state on 2026-05-06: `main...origin/main` ahead 10；untracked `.claude/` and `overlay_ui_context.txt` only; no tracked diff before this memory note.
- Known trap: `README.md` and `run_env.ps1` text are stale in places; prefer `AGENTS.md`, this memory, git log, and actual files.
- Known trap: `overlay_ui_context.txt` is an old UI snapshot and differs from current `scripts/voice_overlay.py`; do not restore from it blindly.
- Hard boundaries still active: no API key in config/docs/logs/code/commit messages, no writes to `E:\DataBase`, no new god manager/controller, no broad refactor unless explicitly scoped.

### V1.3-Overlay-UI-E PySide6 overlay dock（2026-05-06）

- 新增 `src/xiaohuang/voice_overlay_qt_ui.py`（427 行）：PySide6 frameless/topmost/tool 透明窗口，QPainterPath 多层音波，Qt Signal bridge 保证 worker thread 更新 UI 安全。
- `scripts/voice_overlay.py` 从 Tkinter/Pillow 音波实现缩减到 374 行入口/组装；保留 `VoiceOverlayApp` re-export 和 wake runtime 测试兼容常量。
- 删除未引用的 `frontend/voice_overlay/*` HTML prototype 资产；`frontend/control_panel/*` 和 Web 控制面板不变。
- `requirements.txt` 新增 `PySide6>=6.11.0`；未新增其他 GUI 依赖。
- 验证：`voice_overlay.py --help` OK；`compileall -q src scripts tests` OK；`unittest discover -s tests` 539 tests OK；有界 Qt preview smoke 自动打开/关闭，`stop_event_set=True`。

## 历史状态快照（已过期，仅供参考）

以下"当前最新状态"内容曾描述 V1.3-UI-A 阶段（pywebview Web 控制面板原型阶段），现已过时。当前真实状态见顶部 **Current Snapshot（2026-05-06）**。

- **历史阶段**：V1.3-UI-A — pywebview Web 控制面板原型（已过时）
- **历史 commit**：V1.3-UI-A pywebview control panel prototype（见 git log）
- **历史新增**：`control_panel_web_service.py` + `control_panel_web.py` + frontend HTML/CSS/JS + tests
- **分支**：`main...origin/main`
- **工作区**：openWakeWord listener 已从 1 秒短周期改为连续 `run_until_stopped()`
- **测试**：unittest / compileall / voice_overlay、wake_engine_demo、control_panel help 均通过

### V1.3-UI-B Web 控制面板 Control Shell 重做（2026-05-05）

- 重做 index.html（157 行）、style.css（261 行）、app.js（223 行）。
- 新布局：Top Bar + 左侧 Sidebar（10 个导航项） + 主工作区 + 右侧 Diagnostic Drawer。
- 完整 Liquid Glass token 系统（blur/dark-fill/rim/inset-gloss/neon-ring/caustics）。
- 组件类：.glass-card、.glass-pill、.glass-pill-primary、.glass-input、.glass-toggle、.glass-toast。
- reveal 动效（stagger cards 80-140ms）、prefers-reduced-motion 支持。
- 新增 11 个前端结构测试。未改 Python API/control_panel.py/voice_overlay.py。

### V1.3-UI-A pywebview Web 控制面板原型（2026-05-05）

- 新增 `control_panel_web_service.py`（161 行）：`ControlPanelWebApi` class，封装 status/start/stop/restart/save/refresh API。
- 新增 `control_panel_web.py`（82 行）：pywebview 启动器，可选依赖，未安装时友好提示。
- 新增前端：index.html（102 行）、style.css（226 行，Dark Liquid Glass 风格）、app.js（233 行）。
- 复用 `status_control_service` 全部启停/保存逻辑。
- 新增 20 个单测（`tests/test_control_panel_web_service.py`）。
- 旧 `control_panel.py` 保留不变。未改 voice_overlay、runtime services、PowerShell/requirements。

### V1.2H-C overlay runtime import 清理收尾（2026-05-05）

- voice_overlay.py 清理 30+ 未使用 import（688 → **648 行**），overlay_loop_runtime_service.py 清理 8 个未使用 import（338 → **330 行**）。
- 保留 tests 引用的 WAKE_ENGINE_*、_select_wake_engine_runtime、_print_wake_engine_runtime_config、_OpenWakeWordBridgeRuntime 等 re-export。
- compileall / --help 通过。无行为改动。

### V1.2H-B overlay loop runtime 迁移记录（2026-05-05）

- 新建 `overlay_loop_runtime_service.py`（338 行）：`OverlayLoopRuntimeConfig` + `run_overlay_runtime()`。
- 从 voice_overlay.py 迁移 `_run_overlay_loop` 主循环 + OWW listener 调度 + stt_text/OWW 分发 + 回调构建 + error handling + cleanup。
- voice_overlay.py 从 938 → **688 行**（-250 行），达成"入口 + UI + 组装"目标。
- 保留 `_record_openwakeword_command`、`VoiceOverlayApp`、`parse_args`、`main` 在 voice_overlay.py。
- 新增 8 个测试（tests/test_overlay_loop_runtime_service.py）。
- 新增 import 在 Code Size Policy 建议范围内（338 行，100-500）。
- 未改 wake/command/reply/assistant runtime、openWakeWord adapter、control_panel/tray、PowerShell。

### V1.2G-B 清理遗留死代码记录（2026-05-05）

- 删除 `_run_openwakeword_wake_loop_once`（旧 OWW polling 版本，~55 行），生产已通过 `_start_openwakeword_listener` 走连续 listener。
- 删除 `_source_note_for_overlay`（~5 行），生产改用 `reply_pipeline_service._source_note_for_source`。
- 删除冗余测试 `test_openwakeword_wake_event_starts_one_command_recording`（功能已被新 listener 测试覆盖）。
- 改写 `test_command_recording_error` 测 `_record_openwakeword_command` 直接路径。
- 改写 `SourceNoteTests` 测 `reply_pipeline_service._source_note_for_source`。
- voice_overlay.py 1001 → 938 行（-63 行）。482 tests OK。

### V1.2G-A 修复语音回复长度策略记录（2026-05-05）

- `llm_reply_service._shorten_reply()` 不再 30 字硬截断，改为完整句末优先截断（默认 180 字、1-3 句）。
- 新增 `_read_int_env()`、`_get_default_max_reply_chars()`、`_get_default_llm_max_tokens()`。
- 支持 `XIAOHUANG_MAX_REPLY_CHARS`（默认 180）和 `XIAOHUANG_LLM_MAX_TOKENS`（默认 768）环境变量。
- 更新 `build_openai_compatible_chat_request()` 默认 persona，鼓励 2-3 句回复。
- 新增 26 个单测（`tests/test_llm_reply_service.py`）。
- 未改 wake/command/reply/assistant runtime、voice_overlay.py、PowerShell/requirements。

### V1.2F-F-D assistant turn orchestration 抽取记录（2026-05-05）

- `assistant_runtime_service.py` 新增 `AssistantTurnCallbacks`、`run_assistant_turn_from_command()`。
- `voice_overlay.py` 的 inline turn 编排（reply 生成 + session/non-session 分发，~90 行）改为调用 `run_assistant_turn_from_command()`。
- pipeline_config + AssistantSessionCallbacks + AssistantRuntimeCallbacks 提升到 while 循环外构造，每轮复用。
- 新增 9 个单测（tests/test_assistant_runtime_service.py）：空 command、非 session reply、session 分发、tts_error、debug、no tkinter 等。
- 未迁移 _run_overlay_loop 整体、主 while、wake 路径、UI。

### V1.2F-F-C session follow-up loop 抽取记录（2026-05-05）

- `assistant_runtime_service.py` 新增 `AssistantSessionCallbacks`、`AssistantSessionOutcome`、`run_session_followup_loop()`。
- `voice_overlay.py` 的 inline session follow-up loop（~120 行）改为调用 `run_session_followup_loop()`。
- session 行为不变：no_speech retry、exit phrase、max_turns、max_session_seconds、stop_event 退出。
- 新增 9 个单测覆盖正常 followup、no_speech、max_turns、exit phrase、stop event、tts error、state 顺序、disabled config、no tkinter。
- 未迁移 `_run_overlay_loop` 整体、主 while 循环、UI、wake 路径、openWakeWord listener。

### V1.2E-B 控制面板 Wake Engine 配置记录（2026-05-04）

- 控制面板显示当前 `wake.engine`、是否默认 `stt_text`、`fallback_enabled`、`device_index`、`cooldown_seconds`、`sensitivity` 和 openWakeWord label 提示。
- 控制面板新增最小 Wake Engine 配置区：`stt_text` / `openwakeword` 下拉、fallback 勾选、device/cooldown/sensitivity 输入框。
- 保存逻辑在 `status_control_service.save_wake_engine_config()`，只改 `wake.engine`、`fallback_enabled`、`device_index`、`cooldown_seconds`、`sensitivity`，保留其他 JSON 字段。
- 配置文件不存在、非法 device/cooldown/sensitivity 会提示错误，不创建错误路径。
- 保存后提示需要重启；“保存并重启小黄”复用控制面板现有 `run_restart_operation()`。
- 本阶段未修改 `voice_overlay.py` / openWakeWord adapter / wake bridge / PowerShell / requirements，也不打开麦克风或启动 openWakeWord。

### V1.2F-B wake_runtime_service 抽取记录（2026-05-04）

- 新建 `src/xiaohuang/wake_runtime_service.py`：`WAKE_ENGINE_STT_TEXT`/`OPENWAKEWORD`、`WakeEngineRuntimeConfig`/`Plan`、`normalize_wake_engine()`、`build_wake_engine_runtime_config()`、`select_wake_engine_runtime()`、`format_openwakeword_dependency_error()`。
- `voice_overlay.py` 改为从 `wake_runtime_service` import 并以 `_` 别名保持兼容；删除本地重复定义 ~110 行。
- 未迁移 listener 线程、command recording、TTS/reply/session、`WakeEngineLoopStopped`/`RuntimeError`、`_OpenWakeWordBridgeRuntime`、`_print_wake_engine_runtime_config`、`_create_openwakeword_adapter`。
- 新增 12 个纯函数单测，指向 `wake_runtime_service`（normalize/select/fallback/unsupported engine/error format）。
- 本阶段未改 openWakeWord adapter / wake bridge / wake engine / PowerShell / E:\DataBase，不打开麦克风。

### V1.2F-C openWakeWord listener 迁移记录（2026-05-04）

- `wake_runtime_service.py` 扩展：新增 `OpenWakeWordListenerHandle`、`OpenWakeWordBridgeRuntime`（线程安全 bridge）、`create_openwakeword_adapter()`、listener 生命周期函数（`start/run/stop/wait/handle/log`）、辅助函数（`stop_adapter_safely`/`wake_engine_runtime_error`/`_safe_print`/`_log_runtime_message`/`_bool_text`）、`WakeEngineLoopStopped`/`WakeEngineRuntimeError` 异常、`OPENWAKEWORD_QUEUE_POLL_SECONDS`/`OPENWAKEWORD_STATUS_INTERVAL_SECONDS`。
- `voice_overlay.py` 改为从 `wake_runtime_service` import 并以 `_` 别名保持内部兼容；删除本地定义 ~200 行，原 1416 行→1150 行。
- 未迁移 `_record_openwakeword_command`、`_record_command_transcribe`、`_call_overlay_transcription`、`_generate_reply_pipeline_guarded`、`_run_overlay_loop`、`VoiceOverlayApp`、session follow-up。
- 未改 openWakeWord adapter / wake bridge / control_panel / PowerShell / E:\DataBase，不打开麦克风。

### V1.2E continuous openWakeWord listener 修复记录（2026-05-04）

- blocker 现象：`voice_overlay.py` 能打印 `openwakeword_listener_starting/running`，但随后持续 `frames=11 raw=0`，用户说 “hey jarvis” 无唤醒；独立 `wake_engine_demo.py --duration-seconds 20 --debug` 仍可输出 wake_event。
- 新根因：overlay listener 每 1 秒反复 `adapter.run_for_duration()`，每轮重开 stream 并重置 coalescer/模型相关上下文，实际只有 10-11 frames，不等价于独立 demo 的连续监听。
- 修复：`OpenWakeWordAdapter` 新增 `run_until_stopped(stop_event, ...)`，一次 start、一次打开 sounddevice input stream，循环读取直到 stop_event；模型对象保持常驻，stream 在连续监听期间保持打开，finally 释放。
- `voice_overlay.py` 后台 listener thread 改为调用 `run_until_stopped()`；不再按秒刷 `openwakeword_listener_cycle_done`，改为周期性 `openwakeword_listener_status`，包含 device、sample_rate、sensitivity、model_labels、frames、max_label、max_score 和 raw/coalesced/suppressed。
- command recording / TTS active 仍由 bridge 拒绝 wake event，但不再通过 `adapter.stop()` 杀掉连续 listener。
- 单测新增/更新：fake adapter 的 `run_until_stopped` 被调用且 `run_for_duration` 不被 overlay listener 调用；真实 adapter fake stream 验证 `run_until_stopped` 只打开一个 stream 并能上报 model labels / max score；fake event 仍进入 command recorder。

### V1.2E openWakeWord listener 修复记录（2026-05-04）

- 根因：上一版 `voice_overlay.py` 的 openWakeWord 集成仍在 overlay turn loop 里同步创建 adapter 并短时 `run_for_duration()`，没有 overlay-owned background listener 生命周期，导致主程序隔离测试中缺少 listener startup/running/error/cycle 日志，且不够明确证明 listener 持续运行。
- 修复：`voice_overlay.py` 在 `wake.engine=openwakeword` 时创建 daemon listener thread；listener 持续按短窗口循环调用 adapter，把 accepted `WakeEvent` 通过 Queue 投递给 overlay worker。
- accepted event 进入统一 command recorder：overlay worker 从 queue 取事件后调用旧 VAD command recording + STT command 入口，不新增残缺命令流程。
- 日志新增/规范：`wake_engine_selected`、`wake_fallback_enabled`、`wake_device_index`、`wake_cooldown_seconds`、`wake_sensitivity`、`openwakeword_listener_starting`、`openwakeword_listener_running`、`openwakeword_listener_cycle_done`、`openwakeword_listener_error`、`fallback_to_stt_text`、`openwakeword_wake_event`、`openwakeword_bridge_decision`、`command_record_start source=openwakeword`。
- command recording 和 TTS 播放期间通过 bridge state 暂停/屏蔽 openWakeWord event；退出时 stop listener / adapter。
- 单测新增 fake adapter 覆盖 listener thread 启动、连续循环、不打开真实麦克风的 accepted event queue handoff、command/tts active 抑制、listener error fallback 和 fallback disabled safe stop。
- 未修改 PowerShell、requirements、`E:\DataBase`；未下载模型；未训练模型。

### V1.2E openWakeWord feature flag 接入记录（2026-05-04）

- `wake.engine` 默认仍是 `stt_text`；新增 `openwakeword` 仅在 JSON 显式配置后启用，`fallback_enabled=true` 时依赖/运行失败回退旧 STT 文本唤醒。
- `app_config_service.WakeConfig` 新增 `engine`、`fallback_enabled`、`sensitivity`、`cooldown_seconds`、`device_index`、`model_path`、`model_name`。
- `voice_overlay.py` 新增 openWakeWord runtime selection；收到 coalesced `WakeEvent` 后经 `WakeCommandBridge` accepted，先 stop adapter，再进入旧 VAD command recorder。
- command record 期间标记 `command_active`；TTS pipeline 用 guarded callback 标记 `tts_active`，用于屏蔽 wake event 和自唤醒风险。
- openWakeWord adapter runtime error 且 fallback 开启时只回退本轮到 `stt_text`；fallback 关闭时显示错误并保持安全状态。
- 新增 fake 单测覆盖默认旧路径、openwakeword 选择、依赖失败 fallback/error、accepted event 只启动一次 command recorder、command/tts active reject、录音异常后 adapter stopped + command inactive。
- 未修改 PowerShell、requirements、`E:\DataBase`、secrets/logs/audio/model cache；未下载模型；未训练中文“贾维斯”模型。
- 人工验证：先测默认/`stt_text` 旧“贾维斯”，再配 `wake.engine=openwakeword` + device 0 后说 “hey jarvis”，最后改回 `stt_text` 回滚。

### V1.2D-C Wake Command Bridge simulation 记录（2026-05-03）

- 新增 `src/xiaohuang/wake_command_bridge_service.py`：`WakeBridgeDecision`、`WakeCommandBridgeConfig`、`WakeCommandBridgeState`、`WakeCommandBridge`、`FakeCommandStarter`。
- bridge 只接收 `WakeEvent` 并调用注入的 fake command starter；不打开麦克风、不启动 openWakeWord/STT/voice_overlay/LLM/TTS。
- 状态机覆盖 `accepted`、`disabled`、`cooldown`、`command_active`、`tts_active`、`bridge_busy`、`invalid_event`、`recorder_error`；recorder error 会释放 `bridge_busy`。
- 新增 `scripts/wake_command_bridge_demo.py`：默认 `events=3`、`interval_seconds=0.5`、`cooldown_seconds=2.5`，预期只 `command_starts=1`，后续 event 因 cooldown 被 suppress。
- 新增 `docs/V1.2D_C_WAKE_COMMAND_BRIDGE_VALIDATION.md`，记录桥接层目标、状态机、fake 验证、demo 命令、风险和下一步。
- 新增单测覆盖 accepted/cooldown/cooldown 后恢复、command_active、tts_active、disabled、recorder_error、reset、fake starter 只接收 accepted event、demo help/dry-run/default/simulated blocks。
- 未修改 `voice_overlay.py`、`wake_loop_service.py`、`wake_word_service.py`、conversation/TTS/LLM/reply pipeline、openwakeword adapter、控制面板、托盘、PowerShell、requirements；未写 `E:\DataBase`；未打开真实麦克风；未下载模型；未训练中文“贾维斯”模型。
- 下一步 V1.2D-D：只读分析 `voice_overlay.py` 的 command recording 入口，设计 feature flag + 最小接入点；仍不直接替换 STT 文本唤醒。

### V1.2D-B Wake Engine safety validation 记录（2026-05-03）

- `scripts/wake_engine_demo.py` 新增 `--safety-check`、`--repeat`、`--gap-seconds`，重复执行 adapter start / short run / stop，并输出每轮 frames、raw/coalesced/suppressed 统计和 `status_after_stop`。
- `OpenWakeWordAdapter.status()` 区分 `model_loaded` 与 `ready`；模型加载后即保持 `model_loaded=True`，运行错误只影响 `ready/error`，错误摘要增加基础 secret redaction。
- 单测新增覆盖 start 前 stop 幂等、普通异常释放 fake stream、`KeyboardInterrupt` 释放 fake stream、callback 只触发 coalesced event、两轮 fake run 后不残留 `running=True`、fake safety-check 两轮输出。
- 新增 `docs/V1.2D_B_WAKE_ENGINE_SAFETY_VALIDATION.md`，并更新 V1.2 design、V1.2D adapter doc、README。
- 真人 safety-check 已通过：`--engine openwakeword --duration-seconds 10 --device 0 --debug --cooldown-seconds 2.5 --safety-check --repeat 2 --gap-seconds 1`。
- 关键结果：round 2 `frames=123`、`raw_detections=17`、`coalesced_events=3`、`suppressed_detections=14`、`status_after_stop running=false ready=false model_loaded=true error=-`；最终 `all_rounds_completed=true`、`microphone_released=true`、`errors=0`。
- 未修改 `voice_overlay.py`、`wake_loop_service.py`、`wake_word_service.py`、conversation/TTS/LLM/reply pipeline、控制面板、托盘、PowerShell、requirements；未写 `E:\DataBase`；未下载模型；未训练中文“贾维斯”模型。
- 后续已进入 V1.2D-C 并完成 wake event -> fake command starter 模拟桥接；真实 command recorder、TTS pause/cooldown 和 `stt_text` fallback 仍需后续主链路设计/人工验证。

### V1.2D-A OpenWakeWordAdapter harness 记录（2026-05-03）

- 新增 `src/xiaohuang/openwakeword_adapter.py`：`OpenWakeWordDependencyStatus`、`check_openwakeword_dependencies()` 和 `OpenWakeWordAdapter`。
- adapter 模块 import 本身不依赖 openwakeword；依赖检查和 runtime 都是 optional import，不打开麦克风、不加载模型、不下载模型。
- `OpenWakeWordAdapter.start()` 加载 numpy、openWakeWord model 和 sounddevice `InputStream` factory；`run_for_duration()` 才打开 stream，结束或异常时 finally 释放并 `stop()`。
- adapter 复用 `WakeEvent`、`WakeEngineStatus`、`WakeEventCoalescer`、`WakeEventStats`；只对 coalesced event 调用 callback，真实 label 保存在 `WakeEvent.label`，显示名保存在 `wake_phrase`。
- `scripts/wake_engine_demo.py --check-install` 已改为调用 adapter dependency check；真实监听路径优先走 `OpenWakeWordAdapter.run_for_duration()`；`--help` / `--dry-run` 仍不加载模型、不打开麦克风。
- 新增 `docs/V1.2D_OPENWAKEWORD_ADAPTER_VALIDATION.md`，记录 adapter 生命周期、demo 关系、安全边界和 V1.2D-B 前置检查。
- 新增单测覆盖缺依赖不崩溃、依赖模拟齐全、start/stop 幂等、fake model/audio stream、per-label cooldown、`--help` / `--check-install` / `--dry-run`。
- 未修改 `voice_overlay.py`、`wake_loop_service.py`、`wake_word_service.py`、conversation/TTS/LLM/reply pipeline、控制面板、托盘、PowerShell、requirements；未写 `E:\DataBase`；未下载模型；未训练中文“贾维斯”模型。
- 下一步 V1.2D-B：验证麦克风释放、wake event -> command recorder 切换、TTS 播放期间 pause/cooldown、adapter error fallback 到 `stt_text`。

### V1.2C WakeEngine service abstraction 记录（2026-05-03）

- 新增 `src/xiaohuang/wake_engine_service.py`：`WakeEvent`、`WakeEngineStatus`、`WakeEventStats`、`WakeEventCoalescer`、`FakeWakeEngine` 和轻量 `WakeEngine` Protocol。
- `WakeEventCoalescer` 是 per-label cooldown：同一 label 在 cooldown 内只接受第一次 detection，不同 label 不互相抑制；统计 `raw_detections`、`coalesced_events`、`suppressed_detections`，支持 `reset()`。
- `FakeWakeEngine` 不依赖麦克风或 openWakeWord，支持 start/stop/status、fake event emission、cooldown 测试和 error simulation，供 V1.2D 接入前测试使用。
- `scripts/wake_engine_demo.py` 已复用 service 层 `WakeEventCoalescer` / `WakeEventStats` / `WakeEvent`；保留 `--help`、`--check-install`、`--dry-run`、`--list-devices`、`--cooldown-seconds`、`--no-coalesce`。
- 新增 `docs/V1.2C_WAKE_ENGINE_SERVICE_DESIGN.md`，并更新 V1.2A/V1.2B 文档与 README，明确本阶段不接入 `voice_overlay.py`。
- 未新增 `openwakeword_adapter.py`；adapter 边界留到 V1.2D 前安全验证阶段。
- 未修改 `voice_overlay.py`、`wake_loop_service.py`、`wake_word_service.py`、控制面板、托盘、PowerShell、requirements；未新增依赖；未写 `E:\DataBase`；未下载模型；未训练中文“贾维斯”模型。
- 下一步 V1.2D 前置：adapter optional import、安全状态、麦克风释放、命令录音切换、TTS 后 cooldown、自唤醒防护和 STT text fallback rollback。

### V1.2B-1 openWakeWord Event Coalescing 记录（2026-05-03）

- `scripts/wake_engine_demo.py` 增加 `--cooldown-seconds`（默认 2.5）和 `--no-coalesce`；默认按 label 做 per-label cooldown。
- 结束 summary 新增 `raw_detections`、`coalesced_events`、`suppressed_detections`、`cooldown_seconds`；raw detection 仍代表帧级 score 命中，不等于用户喊话次数。
- 用户真人验证：`openwakeword 0.6.0`、`onnxruntime 1.23.2`、`sounddevice 0.5.5`、`numpy 2.2.6` 可用；`pyaudio` / `PyAudioWPatch` 未安装但不影响 sounddevice backend。
- 设备：`--list-devices` 共 12 个 input device；继续用 device 0，因为小黄历史一直用 device 0。
- 模型：初次缺 `alexa_v0.1.onnx`，用户执行 `openwakeword.utils.download_models()` 后默认模型可用；本仓库未提交模型。
- 真人结果：30 秒 demo `listening=true`；英文 `hey_jarvis` 多次成功，score 最高接近 0.998；静默测试 `frames=748, detections=0`；重复唤醒 `frames=373, detections=29`。
- 结论：openWakeWord 本机可行性通过，但 `wake_phrase=贾维斯` 只是显示名，真实 label 是英文 `hey_jarvis`；中文“贾维斯”模型未完成，不接入 `voice_overlay.py`。
- 下一步 V1.2C：`WakeEngine` abstraction + adapter + event coalescing + `stt_text` fallback，先验证麦克风释放、命令录音切换和 TTS 后 cooldown。

### V1.2B openWakeWord 独立 Demo 记录（2026-05-03）

- 新增 `scripts/wake_engine_demo.py`：独立 openWakeWord demo harness，支持 `--help`、`--check-install`、`--dry-run`、`--list-devices`、短时监听参数、score/event 输出路径。
- 新增 `docs/V1.2B_OPENWAKEWORD_DEMO_VALIDATION.md`：记录本机依赖、设备、限制和下一步真人体验方法。
- 当前 `F:\for_xiaohuang\conda310\python.exe` 环境已由用户补齐：`openwakeword 0.6.0`、`onnxruntime 1.23.2`、`numpy 2.2.6` 和 `sounddevice 0.5.5` 已可用；`pyaudio` / `pyaudiowpatch` 未安装。
- `--check-install` 设计为 exit code 0；当前已返回 `openwakeword_installed=true` / `ready_for_realtime_demo=true`。
- `--list-devices` 已能通过 `sounddevice` 列出 12 个 input device；stdout/stderr 设置 errors=replace，避免 Windows 设备名特殊字符导致 GBK 编码崩溃。
- 本阶段未修改 `voice_overlay.py`、`wake_loop_service.py`、`wake_word_service.py`、控制面板、托盘、PowerShell、配置主链路，仓库未新增依赖，未提交模型文件，未训练中文“贾维斯”模型，未写 `E:\DataBase`。
- 后续 V1.2C 前建议：继续用 `wake_engine_demo.py --check-install`、`--list-devices`、短时 `--duration-seconds 30 --debug --cooldown-seconds 2.5` 记录 score/CPU/设备占用，再抽象 WakeEngine service。

### V1.2A Wake Engine 设计记录（2026-05-03）

- 新增 docs-only 设计：`docs/V1.2_WAKE_ENGINE_DESIGN.md`。
- 目标：解决当前 STT 文本匹配唤醒不灵敏、用户需要喊多次的问题，规划专用 Wake Word / KWS 引擎。
- 数据库 API `127.0.0.1:8765` 未运行，按要求只读 `E:\DataBase` curated 文件和本地 raw 项目，未重建索引，未写数据库。
- 本地参考项目：`openWakeWord`、`Wake-Word`、`FunASR`；未找到本地 `wyoming-openwakeword` / `sherpa-onnx` / `mycroft-precise` 独立仓库，已用官方资料补充。
- 推荐路线：V1.2 优先 openWakeWord 独立 demo + adapter 抽象，保留 STT 文本匹配 fallback；Porcupine 只作体验标杆/可选方案，wyoming-openwakeword 只借鉴 server 架构，sherpa-onnx / FunASR KWS 做中长期对比，Precise 只研究。
- 规划新增但本阶段不实现：`src/xiaohuang/wake_engine_service.py`、`src/xiaohuang/openwakeword_adapter.py`、`scripts/wake_engine_demo.py`，后续可选 `scripts/wake_engine_server.py`。
- 明确 V1.2A 不修改 `voice_overlay.py`、wake/session/TTS/LLM router、控制面板、托盘、PowerShell、配置代码，不下载模型，不训练模型，不新增依赖。
- `E:\OpenSourceWakeTest\wake_projects_install_report.md` 不存在；待 V1.2B 独立实验补充安装和麦克风验证结果。

### V1.1.4D 设计记录（2026-05-03）

- 新增 docs-only 设计：`docs/V1.1.4D_STATUS_CONTROL_PANEL_DESIGN.md`。
- 目标：解决托盘启动后用户看不见 readiness 的问题，明确显示 STT server、health/model_loaded、voice_overlay、config 摘要和 `can_wake_now`。
- 推荐后续实现：`scripts/control_panel.py` + `src/xiaohuang/status_control_service.py`，可选 `status_types.py`。
- 控制面板应复用 `launch_control_service.py` 的进程检测、health check、readiness、启停命令，不复制 PowerShell 解析逻辑。
- 技术方案推荐 Tkinter，暂不引入 PySide6 / Qt / WebView / Tauri。
- 数据库参考：code-assets-global-index、code-asset-reuse-rules、launch-control-readiness-pattern、operation-lock snippet、desktop assistant adapter、settings-ui-config-validation、backend-healthcheck-error-envelope。
- 明确 V1.1.5 后续再规划后台常驻、STT server 常驻、暂停/恢复监听、完全退出和开机自启。
- 本阶段未修改 `.py` / `.ps1` / `.json` / `.yaml` / `src` / `scripts` / `tests`，未写 `E:\DataBase`。

### V1.1.4D-A 实现记录（2026-05-03）

- 新增 `src/xiaohuang/status_control_service.py`：聚合 `launch_control_service` 的进程检测、STT health、配置摘要，返回 `ControlPanelStatus`。
- 新增 `scripts/control_panel.py`：Tkinter 基础控制面板，支持 `--config` 和 `--refresh-interval`，显示总状态、STT/overlay/health、助手名、唤醒词、LLM provider、TTS 和 config path。
- 控制面板支持启动/停止/重启、刷新状态、打开设置、打开日志目录；操作在后台线程执行，关闭窗口不停止小黄。
- `scripts/tray_app.py` 菜单新增“打开控制面板”，原有启动/停止/重启/退出托盘语义不变。
- 未修改 PowerShell、`voice_overlay.py`、wake/session/TTS/LLM 主链路，未新增依赖，未写 `E:\DataBase`。
- 自动验证：315 tests OK、compileall OK、control_panel/tray_app/settings_ui/voice_overlay help OK；人工验证仍需用户从托盘打开控制面板并真实启动/唤醒/重启/停止。

### V1.1.4D-A readiness 修复记录（2026-05-03）

- 修复 blocker：UI 已显示 READY 时，启动/重启操作仍返回 `timeout_voice_overlay_missing` 的不一致。
- 根因：`voice_overlay.py` 命令行分类没有完整规范化路径形式，且启动/重启等待超时后没有用控制面板最终 READY 状态兜底。
- `launch_control_service.classify_process_command_line()` 现在支持绝对路径、相对 `scripts\...`、正斜杠、带引号和 `pythonw.exe` 形式；其他项目绝对路径同名脚本仍不计入。
- `wait_until_ready()` 增加可注入 compact poll 文本：`readiness poll stt=True overlay=True health=ready model_loaded=True`，单测不写真实日志。
- `status_control_service` 启动/重启在 wait timeout 后会重读 `build_status()`；若 `can_wake_now=True`，返回成功，避免 READY 后误弹未就绪错误。
- READY 条件统一为 STT 进程 + overlay 进程 + `/health` ready（`status=ready` 或 `model_loaded=True`）。
- 未修改 PowerShell、`voice_overlay.py`、wake/session/TTS/LLM router，未新增依赖，未写 `E:\DataBase`。
- 自动验证：315 tests OK、compileall OK、control_panel/tray_app/settings_ui/voice_overlay help OK。

### V1.1.4D-B 控制面板流畅性修复记录（2026-05-03）

- 根因确认：`scripts/control_panel.py` 的周期刷新原先在 Tkinter 主线程调用 `build_status()`，会触发 PowerShell 进程检测和 STT `/health` 网络请求，导致拖动/点击卡顿。
- 修复：新增 `StatusRefreshController`，周期刷新、手动刷新和操作后刷新都改为后台线程采集状态，再用 `root.after(0, ...)` 回主线程渲染。
- 防堆叠：状态中新增 `refresh_in_progress`、`pending_refresh`、`refresh_generation`、`last_status`；旧 generation 的刷新结果不会覆盖较新的操作/READY 状态。
- 启动/停止/重启仍在后台执行；操作 worker 结束后顺便采集 `final_status`，READY 时继续消除陈旧 `timeout_voice_overlay_missing` 弹窗。
- 关闭窗口安全：`closed=True` 后刷新结果不再更新 Tk 控件，关闭时递增 generation 丢弃旧结果。
- 真人复测发现 D-B 仍有 READY 界面 + `timeout_voice_overlay_missing` 错误弹窗竞态；后续修复为 operation completion result 优先：worker 用短暂 grace window 采集 READY `final_status`，主线程只按该 final_status 决定启动/重启弹窗，operation completion pending 时普通 refresh apply 会被跳过。
- 未修改 PowerShell、`voice_overlay.py`、wake/session/TTS/LLM router，未新增依赖，未写 `E:\DataBase`。
- 数据库参考：读取 code assets global index、reuse rules、`launch-control-readiness-pattern.asset.json`、operation-lock snippet、desktop assistant adapter；本机数据库 API `127.0.0.1:8765` 未运行，改为按要求只读文件。
- 自动验证：`F:\for_xiaohuang\conda310\python.exe`（Python 3.10.20）下 334 tests OK、compileall OK、control_panel/tray_app/settings_ui/voice_overlay help OK；此前 `.venv` fallback 也通过基础 D-B 命令。

### V1.1.3C 验证收尾记录（2026-05-02）

- Settings UI 可打开，6 个 tab 齐全：Wake / Assistant / LLM / TTS / Conversation / Advanced。
- 人工保存 `assistant.display_name = 贾维斯测试` 后发现 blocker：Advanced 页 `post_response_cooldown=None` 被保存成字符串 `"None"`。
- 根因：Tkinter Entry 初始化时 `str(None)` 显示为 `"None"`，保存层未把 `"None"` / 空字符串规范成 JSON `null`。
- 修复：`scripts/settings_ui.py` 将 None 显示为空；`settings_config_file_service.normalize_ui_inputs()` 将 `overlay.post_response_cooldown` 的空值/`None`/`null` 规范为 `None`，数字字符串转 float。
- 已修复测试配置：`%USERPROFILE%\.xiaohuang\config_settings_ui_test.json` 中 `overlay.post_response_cooldown` 已恢复为 JSON `null`。
- 真实启动验证显示 `wake.phrases=贾维斯`、LLM persona、TTS、session exit 都生效；日志有 `source=llm`、`Session ended: reason=exit_phrase`，无 Traceback/ERROR/TypeError。
- 追加小修：浮窗内部状态文案不再硬编码“小黄”，会使用 `assistant.display_name` 和第一个 `wake.phrases`；默认仍保持“小黄”。
- 最终真人验证已通过：Settings UI 保存后的 `config_settings_ui_test.json` 可真实启动小黄；“贾维斯”可唤醒，`assistant.display_name` 生效，问“你是谁”保持贾维斯身份，TTS 有声音，session exit 正常。
- 日志检查无 Traceback / ERROR / HTTPError / TypeError / UnboundLocalError。
- 详细记录见 `docs/V1.1.3C_SETTINGS_UI_VALIDATION.md`。

### V1.1.4A 设计记录（2026-05-02）

- 目标：让小黄从手动命令启动演进为可由托盘管理的桌面常驻助手。
- 本阶段只设计，不写托盘代码，不改 `.py/.ps1/.json/.yaml` 运行文件。
- 设计覆盖：启动/停止/重启小黄、打开 Settings UI、打开 logs 目录、状态显示、安全退出、进程识别、配置路径、日志、风险和验收。
- 推荐入口：未来新增 `scripts/tray_app.py`；可选服务 `process_status_service.py` / `launch_control_service.py`。
- 详细设计见 `docs/V1.1.4_TRAY_LAUNCH_CONTROL_DESIGN.md`。

### V1.1.4B 实现记录（2026-05-02）

- 新增 `scripts/tray_app.py`，使用 pystray + Pillow 创建最小托盘入口。
- 菜单只包含：打开设置、打开日志目录、关于/状态、退出托盘。
- `打开设置` 调用当前 Python 运行 `scripts/settings_ui.py --config <config_path>`，不阻塞托盘主线程。
- `打开日志目录` 创建并打开 `logs/`。
- `退出托盘` 只停止托盘图标，不调用 `stop_xiaohuang.ps1`，不停止 STT/overlay。
- 新增依赖：`pystray>=0.19.5`、`Pillow>=10.0`。
- 自动验证：267 tests OK、compileall OK、tray/settings/overlay help OK。
- 启动 smoke：`tray_app.py --config config_settings_ui_test.json` 可启动为常驻进程。
- 最终真人验证已通过：托盘图标出现、右键菜单打开、打开 Settings UI、读取 `config_settings_ui_test.json`、打开 `logs/`、关于/状态、退出托盘均正常。
- 边界验证通过：V1.1.4B 没有启动/停止/重启小黄；退出托盘不会停止 STT server / voice_overlay；未影响 voice_overlay / wake / session / TTS / LLM router 主链路。
- 详细记录见 `docs/V1.1.4B_TRAY_VALIDATION.md`。

### V1.1.4C 实现记录（2026-05-02）

- 新增 `src/xiaohuang/launch_control_service.py`，封装 PowerShell 启停命令构造、重启顺序、日志目录、进程检测和状态摘要。
- `scripts/tray_app.py` 菜单新增：启动小黄、停止小黄、重启小黄。
- 启动小黄会先检测 STT server / voice_overlay；只有二者都存在才提示“已在运行”，避免重复启动。
- 启动命令会传递当前托盘 `--config` 到 `start_xiaohuang.ps1 -ConfigPath <config_path>`，避免丢失 `config_settings_ui_test.json`。
- 停止命令调用 `stop_xiaohuang.ps1 -StopSttServer`；退出托盘仍只退出托盘程序，不停止小黄。
- 本阶段未修改 PowerShell、voice_overlay、wake、session、TTS、LLM router，也未新增依赖。
- 自动验证：274 tests OK、compileall OK、tray_app/settings_ui/voice_overlay help OK；托盘进程受控启动 5 秒 smoke 后按 PID 停止，未触发小黄启动/停止菜单。
- Blocker 修复：用户发现托盘启动后只有 `voice_overlay.py`、没有 `stt_server.py`，`/health` 连接拒绝；根因是启动防重复逻辑用 `any_running`，overlay-only partial 状态被误判为已运行并跳过完整启动。
- 修复策略：新增 `ProcessStatus.is_fully_running` / `is_partial` 和 `build_start_sequence_for_status()`；partial/broken 状态下“启动小黄”先调用 `stop_xiaohuang.ps1 -StopSttServer` 清理，再调用 `start_xiaohuang.ps1 -ConfigPath <config_path>` 完整拉起链路。
- PowerShell 调用 blocker：`powershell.exe -File start_xiaohuang.ps1` 会在 dot-source `run_env.ps1` 时解析示例命令里的 `&` / 引号失败；同一 argv list 用 `pwsh.exe` 可正常拉起 STT server 和 overlay。
- 修复策略：启停命令仍返回 argv list、仍用 `-File`、仍 `shell=False`，但优先解析 `pwsh.exe`，找不到才回退 `powershell.exe`；不修改 `start_xiaohuang.ps1` / `stop_xiaohuang.ps1` / `run_env.ps1`。
- Readiness 修复：启动/重启不再只看 PowerShell returncode；必须等待 STT server 进程、voice_overlay 进程和 `/health` ready/model_loaded。
- 防重复点击：`scripts/tray_app.py` 新增 `OperationGuard`，启动/停止/重启同一时间只允许一个操作线程；重复点击只提示当前操作进行中。
- 停止确认：停止命令完成后等待 STT server / voice_overlay 都消失；超时提示查看 `logs/tray_app.log`。
- Operation release 修复：用户确认没有残留 pwsh/powershell 启停脚本进程，但托盘仍显示“启动操作进行中”；修复为 `_execute_guarded_operation()` 统一 acquire/release，所有 success/error/timeout/exception 路径都在 finally 中释放，并记录 `operation=<name> release reason=<...>`。
- 启动命令改为 async 发出后直接 wait readiness；readiness 成功即可释放 busy flag，不再等待 `start_xiaohuang.ps1` 进程完全退出作为唯一成功条件。

### V1.1.3B 真实验证结果（2026-05-02）

| 验证项 | 结果 | 证据 |
|--------|------|------|
| Provider Router 链路 | ✅ | `Overlay reply: 我是贾维斯，你的桌面语音助手。 (source=llm)` |
| llm_ms 延迟追踪 | ✅ | latency summary 含 llm_ms |
| TTS 合成 + 播放 | ✅ | tts_synthesis_ms + tts_playback_ms 出现 |
| llm.enabled=false 边界 | ✅ | source=rule |
| missing key fallback | ✅ | source=rule_fallback_no_key，不崩溃，不泄露 key |
| Session 正常结束 | ✅ | Session ended: reason=exit_phrase |
| 无异常 | ✅ | 无 Traceback/ERROR/HTTPError/TypeError/UnboundLocalError |
| 贾维斯 identity | ✅ | 问"你是谁" → 自称"贾维斯"（非"小黄"） |

其他 provider（qwen/doubao/openai_compatible）已通过 11 个单元测试覆盖，真实 API 验证待用户配置对应 key。

### V1.1.3A 已完成

- 用户配置中控层 `app_config_service.py`（`XiaoHuangConfig` dataclass，8 个配置段）
- `--config` / `-ConfigPath` 打通
- `wake.phrases` 自定义唤醒词（完全替换默认值）
- `tts.voice` 配置
- `conversation` 参数配置
- `assistant.name` / `display_name` / `persona` 配置（V1.1.3A.4）
- `wake.phrases` 与 `assistant.name` 独立
- `llm` provider/model/base_url/api_key_env 预留
- `config.json` 不存 API key，只存 `api_key_env`
- `secrets.ps1` 仍加载
- PowerShell 不再用默认值覆盖 config
- 配置优先级：CLI > config.json > 默认值

### V1.1.3A 文档

- `docs/configuration.md` — 用户配置字段参考
- `docs/V1.1.3A_CONFIG_AUDIT.md` — 中控层收口审计

## 已踩坑（V1.1.3A 修复记录）

| # | 现象 | 根因 | 修复 commit |
|---|------|------|------------|
| 1 | `TypeError: 'XiaoHuangConfig' object is not subscriptable` | 新旧 `load_config` 同名覆盖；dataclass 被当作 dict 访问 | `af77b75` |
| 2 | `store_true` 的 `False` 覆盖 config 的 `true` | argparse `action="store_true"` 默认 `False`，直接赋值覆盖 | `cdeb5e5`（内建 `_or_config`） |
| 3 | `UnboundLocalError: local variable 'debug' referenced before assignment` | `debug = app_config.runtime.debug` 在 `apply_cli_overrides` 之前执行 | `cd1e218` |
| 4 | PowerShell 默认 `$Device = 0` 覆盖 `config.json` 的 `audio.device_id` | PS 参数默认值始终传入 Python | `763e566` + `50a3823` |
| 5 | argparse `--wake-phrases default="小黄,小黄小黄"` 覆盖 config | argparse 的 `default` 在未传参时生效 | `7beee12` |
| 6 | 唤唤醒"贾维斯"后助手自称"小黄" | `build_deepseek_request` 硬编码 system prompt | `67583d8` |

## 下一阶段建议

| 版本 | 内容 |
|------|------|
| V1.1.3B | LLM Provider Router ✅ 已完成 |
| V1.1.3C | Settings UI Prototype ✅ 最终真人验证通过，阶段性收口 |
| V1.1.4B | 最小托盘入口 ✅ 已实现并真人验证通过 |
| V1.1.4C | 托盘启动 / 停止 / 重启控制，自动验证后需真人验证 |
| V1.2 | Wake Engine Abstraction |

---

## 历史阶段

<details>
<summary>V0.9.1 — DeepSeek 单句对话原型（收尾稳定版）</summary>

- Purpose: XiaoHuang V0.9.1 is a stabilization patch over V0.9 — DeepSeek error handling, LLM reply cleaning, TTS/LLM combination stability, artifact protection, and docs.
- V0.9.1 scope: no new features, no backend foundation, no multi-turn memory, no tool execution.
- V0.9.1 changes:
  - LLM reply execution claim filter (blocks "我已经打开"/"已下载"/"已执行" etc.)
  - Expanded tool request keywords (17 categories)
  - Overlay result displays fallback source note when DeepSeek unavailable
  - Improved shutdown: exception handler checks stop_event before sleeping
  - No-key startup message only in debug mode, not every round
  - API key never logged or included in reply text
  - Reply source tracked and displayed: llm/rule/rule_fallback_no_key/rule_fallback_error/tool_unavailable
- Key files: `scripts/voice_overlay.py`, `scripts/wake_loop.py`, `scripts/test_wake_text.py`, `src/xiaohuang/llm_reply_service.py`, `src/xiaohuang/reply_service.py`, `src/xiaohuang/tts_service.py`, `src/xiaohuang/wake_word_service.py`, `src/xiaohuang/wake_loop_service.py`.
- Current environment: use `F:\for_xiaohuang\conda310\python.exe`; recording works with `device 0`; ModelScope cache is `F:\for_xiaohuang\models\modelscope`; ffmpeg is installed through `winget` and available on PATH.
- Startup/test: dot-source `.\scripts\run_env.ps1`; set `PYTHONPATH=E:\Projects\xiaohuang\src`; run `& "F:\for_xiaohuang\conda310\python.exe" -m unittest discover -s tests`.
- Last completed: V0.9.1 stabilization — 81 tests pass (9 new), compileall clean, --help verified.
- Overlay command: `& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --device 0 --debug`.
- API key boundary: never commit or write `DEEPSEEK_API_KEY`; use environment variables only.
- Wake trap: V0.9.1 wake is short-recording + STT text matching, not openWakeWord/FunASR KWS.
- Still unfinished at V0.9.1: real KWS model, multi-turn dialogue, system tray, installer, desktop-assistant integrations.

</details>

<details>
<summary>V1.1.x 演进</summary>

| 版本 | Commits | 内容 |
|------|---------|------|
| V1.1.1D/E | `4cfb9a1`~`5db0e11` | command STT mode, session exit import, empty speech handling, TTS background playback |
| V1.1.2A/B/C | `652c00d`~`3b9f683` | latency metrics, adaptive follow-up session, session UI state fixes, session logs |
| V1.1.3A | `cdeb5e5`~`67583d8` | user config foundation, PowerShell respect config, dataclass/CLI/wake bug fixes, assistant identity |

</details>

## 运行环境（不变）

- Python: `F:\for_xiaohuang\conda310\python.exe`
- 麦克风: `device 0`
- 模型缓存: `F:\for_xiaohuang\models\modelscope`
- STT: FunASR / SenseVoiceSmall
- Git ignore: `data/recordings/*.wav`, `data/recordings/wake/`, `data/tts/`, `logs/`, `models/`, `.venv/`, `__pycache__/`
