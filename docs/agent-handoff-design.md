# Agent Handoff Design

## Why Agent Handoff

XiaoHuang already understands confirmed text tasks and readonly reports. The next step is to help the user prepare work for engineering agents without launching those agents directly. Agent Handoff turns a natural-language request into a structured prompt draft that can be copied into Claude Code, Codex, OpenClaw, opencode, or another agent.

## C1 Minimum Scope

C1 only generates a handoff draft text file. It does not open terminals, run shell commands, start agent programs, modify `E:\DataBase`, or browse the web. It may call the local readonly database brief API at `http://127.0.0.1:8765/brief`; if that API is unavailable, it still generates a normal prompt.

## Data Flow

1. Chat text is parsed by `text_task_intent_service`.
2. Agent handoff requests become `agent_handoff_draft` pending tasks.
3. The existing registry requires user confirmation.
4. `text_task_execution_service` calls `agent_handoff.service.create_agent_handoff()`.
5. The service routes database domains, optionally fetches `/brief`, builds the prompt, and writes `runtime/agent_handoffs/*.txt`.
6. The result returns a summary, path, target agent, domains, database status, and prompt preview.
7. The existing task result history stores only the safe summary/path/preview, not the full prompt.

## Module Structure

- `models.py`: request, database brief, and result dataclasses.
- `intent_parser.py`: handoff intent and target agent detection.
- `domain_router.py`: rule-based database domain selection.
- `database_brief_client.py`: localhost-only `/brief` client with safe fallback.
- `prompt_builder.py`: structured prompt template.
- `handoff_file_service.py`: UTF-8 file persistence under `runtime/agent_handoffs/`.
- `service.py`: orchestration entry point.

## Database API Boundary

The database client only accepts `http://127.0.0.1` or `http://localhost` endpoints. It sends a short query and domain list to `/brief`, truncates the returned brief, and treats errors/timeouts as `unavailable`. It never reads `E:\DataBase` files directly and never contacts external hosts.

## Safety Boundary

Agent Handoff is a draft generator. It writes one `.txt` file in runtime output and does not execute commands, start agents, open terminals, delete files, move files, download data, or perform browser automation. Prompt text includes explicit warnings against dangerous commands and unrelated edits.

## Prompt Quality

C1.2 separates the user's wrapper request from the real engineering task. For example, "给 Claude Code 生成一个提示词，让它继续优化小黄任务历史页面" keeps the original request for traceability, but the generated prompt title and main task become "继续优化小黄任务历史页面". The prompt package includes suggested files, database rule translation, concrete execution requirements, and acceptance criteria so the target agent acts on the engineering task instead of generating another prompt.

## Copy UX

C1.3 keeps Agent Handoff as a draft-only workflow but makes the generated prompt easier to copy from Chat. The control panel exposes a readonly `read_agent_handoff_file` API that only reads UTF-8 `.txt` files under `runtime/agent_handoffs/` and rejects absolute paths, `..` escapes, non-text files, missing files, and oversized files. The Chat result card can copy the full prompt, the relative handoff path, or the visible preview without opening terminals or launching agents.

## Completion Report Review

C2 closes the handoff loop by recognizing an Agent completion report pasted back into Chat as `agent_completion_review`. The review parser extracts the task title, changed files, implemented items, safety claims, verification claims, manual acceptance notes, commit hash, and commit message from Chinese or English structured text.

The review is intentionally text-only. It does not query GitHub, run `git show`, run shell commands, open terminals, launch agents, or read `E:\DataBase`. Risk rules classify the report as `keep`, `needs_review`, `reject`, or `insufficient`, then the result card shows a concise acceptance summary, risk points, and next steps. Task history stores only the generated review excerpt with `result_kind=agent_review`; it does not store the raw pasted report. The user remains the final reviewer.

## Generic Project Handoff

C3 upgrades Agent Handoff from a XiaoHuang-only prompt generator into a generic project task package generator. `AgentHandoffRequest` now separates the XiaoHuang project root from the target project path with `target_project_path`, `target_project_kind`, and `project_relation`. XiaoHuang still writes handoff files only under its own `runtime/agent_handoffs/`, but the generated prompt can tell Claude Code / Codex to work in an external project such as `E:\Projects\wine-ui`.

Domain routing no longer defaults every handoff to `xiaohuang_project`. XiaoHuang-specific database context is included only when the request is actually about XiaoHuang, while UI/front-end/brand/site tasks route to `ui_design` plus `agent_workflow`. If the user says the task is unrelated to XiaoHuang or asks not to modify XiaoHuang, the prompt explicitly states that the target agent must not modify `E:\Projects\xiaohuang`.

External project prompts use external file suggestions such as `package.json`, `src/App.*`, `src/main.*`, `src/index.css`, `vite.config.*`, and `tailwind.config.*` instead of XiaoHuang control-panel files. If the external target path is missing, the prompt instructs the target agent to ask the user to confirm the path before making changes.

## Why Not Auto-Launch Agents

Auto-launching engineering agents crosses from low-risk prompt generation into local process execution. C1 keeps the workflow reviewable: the user can inspect and copy the prompt before any external agent acts.

## Roadmap

- C1: Database-Aware Agent Handoff Draft
- C2: Completion Report Review
- C3: Generic Project Agent Handoff
- C3.1: Agent Handoff Result UI Polish
- C4: Open Project Terminal + Copy Prompt
- C5: Whitelisted Agent Launcher
- C6: Commit/GitHub Review Assist
- C7: Multi-Agent Workflow Board
