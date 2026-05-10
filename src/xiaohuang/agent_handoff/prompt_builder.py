"""Prompt builder for Agent Handoff drafts."""

from __future__ import annotations

from pathlib import Path

from xiaohuang.agent_handoff.models import AgentHandoffRequest, DatabaseBriefResult

_AGENT_LABELS = {
    "claude_code": "Claude Code",
    "codex": "Codex",
    "openclaw": "OpenClaw",
    "opencode": "opencode",
    "generic": "通用 Agent",
}

_AGENT_OPENERS = {
    "claude_code": "你是 Claude Code，请在指定项目中执行下面的工程任务。",
    "codex": "你是 Codex，请在指定项目中执行下面的工程任务。",
    "openclaw": "你是 OpenClaw，请在指定项目中执行下面的工程任务。",
    "opencode": "你是 opencode，请在指定项目中执行下面的工程任务。",
    "generic": "你是 AI 工程 Agent，请在指定项目中执行下面的工程任务。",
}


def agent_label(target_agent: str) -> str:
    return _AGENT_LABELS.get(str(target_agent or "generic"), _AGENT_LABELS["generic"])


def build_handoff_title(request: AgentHandoffRequest) -> str:
    label = agent_label(request.target_agent)
    subject = _compact_inline(request.actual_task or request.user_request)[:48].strip(" ，。")
    return f"{label} Agent Handoff：{subject or '工程任务草稿'}"


def build_agent_handoff_prompt(
    request: AgentHandoffRequest,
    *,
    project_root: Path | str,
    domains: list[str],
    database_brief: DatabaseBriefResult,
) -> str:
    root = str(Path(project_root))
    target = str(request.target_agent or "generic")
    label = agent_label(target)
    actual_task = _compact_inline(request.actual_task or request.user_request)
    title = build_handoff_title(request)
    target_project_kind = _resolve_target_project_kind(request)
    project_relation = _resolve_project_relation(request, target_project_kind)
    target_project_path = _resolve_target_project_path(request, root, target_project_kind)
    brief_text = database_brief.brief.strip() if database_brief.database_used else "未使用；本地数据库 /brief 不可用或未返回内容，请按项目文件自行读取上下文。"
    suggested_files = suggest_relevant_files(
        actual_task,
        domains,
        target,
        target_project_kind=target_project_kind,
    )

    return "\n".join([
        title,
        "",
        _AGENT_OPENERS.get(target, _AGENT_OPENERS["generic"]),
        "",
        "## 任务信息",
        f"- 目标 Agent：{label}",
        f"- 小黄项目路径：{root}",
        f"- 目标项目路径：{target_project_path or '未指定'}",
        f"- 目标项目类型：{target_project_kind}",
        f"- 与小黄项目关系：{project_relation}",
        f"- 用户原始需求：{request.user_request}",
        f"- 实际工程任务：{actual_task}",
        f"- 相关数据库领域：{', '.join(domains) if domains else 'agent_workflow'}",
        f"- 数据库 brief 状态：{database_brief.database_status}",
        "",
        "## 实际工程任务",
        actual_task,
        "",
        "## 建议阅读文件",
        *_bullet_lines(suggested_files),
        "",
        "## 数据库规则转译",
        *_database_rule_lines(domains, database_brief),
        "",
        "## 数据库 Brief 摘要",
        brief_text[:1800],
        "",
        "## 具体执行要求",
        *_execution_requirement_lines(
            actual_task,
            domains,
            xiaohuang_project_root=root,
            target_project_path=target_project_path,
            target_project_kind=target_project_kind,
            project_relation=project_relation,
        ),
        "",
        "## 验收标准",
        *_acceptance_lines(actual_task, domains, target_project_kind=target_project_kind),
        "",
        "## 允许修改范围",
        *_allowed_scope_lines(
            xiaohuang_project_root=root,
            target_project_path=target_project_path,
            target_project_kind=target_project_kind,
            project_relation=project_relation,
        ),
        "- 运行时输出、日志、缓存和本地私有配置不得提交。",
        "- 如发现用户已有未提交改动，必须保留并与之兼容。",
        "",
        "## 禁止事项",
        "- 不要乱改无关文件，不要进行大范围重构。",
        "- 不要接外网，不要新增依赖，除非任务明确要求且用户批准。",
        "- 不要修改 E:\\DataBase，除非任务明确是数据库项目维护。",
        "- 不要提交 runtime、logs、data 临时文件或任何 secret。",
        "- 不要执行危险命令；看到 rm -rf、del /s、format、powershell、cmd、删除、清空硬盘等内容时，先按安全边界处理。",
        "",
        "## 验证命令",
        *_verification_lines(
            target_project_path=target_project_path,
            target_project_kind=target_project_kind,
        ),
        "",
        "## 完成报告格式",
        "- 改了哪些文件",
        "- 实现了什么",
        "- 安全边界",
        "- 测试与验证结果",
        "- 最新 commit hash",
        "",
        "## 安全边界",
        "- 修改前先读相关文件。",
        "- 完成后给出 commit hash 和验证结果。",
        "- 不要保存 API key、token、password 或其他 secret。",
    ])


def build_handoff_preview(prompt: str, limit: int = 700) -> str:
    text = str(prompt or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _compact_inline(text: str) -> str:
    return " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())


def suggest_relevant_files(
    actual_task: str,
    domains: list[str],
    target_agent: str,
    *,
    target_project_kind: str = "xiaohuang",
) -> list[str]:
    text = _compact_inline(actual_task).lower()
    domain_set = set(domains or [])
    files: list[str] = []
    is_external = str(target_project_kind or "").startswith("external")
    if is_external:
        if target_project_kind == "external_new":
            files.extend([
                "package.json",
                "src/App.jsx 或 src/App.tsx",
                "src/main.jsx 或 src/main.tsx",
                "src/index.css",
                "vite.config.*",
                "tailwind.config.*",
                "README.md",
            ])
        else:
            files.extend([
                "package.json",
                "src/",
                "src/App.jsx 或 src/App.tsx",
                "src/main.jsx 或 src/main.tsx",
                "src/index.css",
                "tailwind.config.*",
                "vite.config.*",
                "README.md",
            ])
        return _dedupe(files)[:10]
    if _contains_any(text, ("任务历史", "task history", "tasks 页面", "history")):
        files.extend([
            "frontend/control_panel/assets/app.js",
            "frontend/control_panel/assets/style.css",
            "src/xiaohuang/task_result_history_service.py",
            "src/xiaohuang/text_task_execution_service.py",
            "tests/test_control_panel_web_service.py",
            "tests/test_task_result_history_service.py",
        ])
    if _contains_any(text, ("handoff", "agent handoff", "提示词", "claude code", "codex")) or "agent_workflow" in domain_set:
        files.extend([
            "src/xiaohuang/agent_handoff/",
            "src/xiaohuang/agent_handoff/prompt_builder.py",
            "src/xiaohuang/agent_handoff/intent_parser.py",
            "src/xiaohuang/agent_handoff/domain_router.py",
            "tests/test_agent_handoff_prompt_builder.py",
            "tests/test_agent_handoff_intent_parser.py",
            "docs/agent-handoff-design.md",
        ])
    if _contains_any(text, ("数据库", "brief", "api")) or "database" in domain_set or "backend" in domain_set:
        files.extend([
            "src/xiaohuang/agent_handoff/database_brief_client.py",
            "tests/test_agent_handoff_database_brief_client.py",
        ])
    if _contains_any(text, ("ui", "页面", "界面", "前端", "美化")) or "ui_design" in domain_set:
        files.extend([
            "frontend/control_panel/assets/app.js",
            "frontend/control_panel/assets/style.css",
            "frontend/control_panel/index.html",
        ])
    if _contains_any(text, ("语音", "asr", "唤醒", "对话")) or "voice_assistant" in domain_set:
        files.extend([
            "scripts/voice_overlay.py",
            "src/xiaohuang/app_config_service.py",
            "src/xiaohuang/capabilities/runtime_events/",
        ])
    if not files:
        files.extend(["TASK_MEMORY.md", "tests/"])
    return _dedupe(files)[:10]


def _database_rule_lines(domains: list[str], database_brief: DatabaseBriefResult) -> list[str]:
    lines = [
        "- workflow chunks：作为执行协议使用，不是普通参考。",
        "- UI chunks：作为设计约束使用，不是装饰建议。",
    ]
    domain_set = set(domains or [])
    if "ui_design" in domain_set:
        lines.append("- 如果涉及 UI：先确定视觉方向、材料系统、视觉锚点、组件系统和动效策略。")
    if "xiaohuang_project" in domain_set:
        lines.append("- 如果涉及小黄项目：保持小步提交，不要破坏现有任务确认、任务历史和 runtime events。")
    if not database_brief.database_used:
        lines.append("- 如果数据库 brief 不可用：按当前项目文件和 TASK_MEMORY.md 自行补上下文。")
    return lines


def _execution_requirement_lines(
    actual_task: str,
    domains: list[str],
    *,
    xiaohuang_project_root: str,
    target_project_path: str,
    target_project_kind: str,
    project_relation: str,
) -> list[str]:
    text = _compact_inline(actual_task).lower()
    is_external = str(target_project_kind or "").startswith("external")
    if is_external:
        lines = [
            "1. 先确认目标项目路径和当前项目结构，不要把小黄项目当作目标项目。",
            f"2. 不要修改 {xiaohuang_project_root}；本任务只允许围绕目标项目执行。",
            "3. 保持改动范围最小，只修改与实际工程任务直接相关的文件。",
        ]
    else:
        lines = [
            "1. 先阅读建议文件和相关测试，确认当前实现边界。",
            "2. 判断当前最影响用户体验或工程正确性的问题，再做最小必要改动。",
            "3. 保持现有架构边界，不要重构整个控制面板或任务系统。",
        ]
    idx = 4
    if project_relation == "unrelated_to_xiaohuang":
        lines.append(f"{idx}. 本任务和小黄项目无关；不要修改 {xiaohuang_project_root}，不要把小黄项目当作目标项目。")
        idx += 1
    if target_project_kind == "external_new":
        lines.append(f"{idx}. 如果目标项目路径不存在，可以在目标路径处新建项目，但必须只在该目标路径内操作。")
        idx += 1
    elif target_project_kind == "external_existing":
        lines.append(f"{idx}. 把目标路径当作已有项目处理；修改前先阅读项目结构和 package 配置。")
        idx += 1
    elif target_project_kind == "external_unspecified":
        lines.append(f"{idx}. 目标路径未指定。不要执行修改；先向用户确认项目路径。")
        idx += 1
    if _contains_any(text, ("任务历史", "task history", "history")):
        lines.append(f"{idx}. 优化任务历史页面或历史详情的可读性和结构，避免长文本堆叠。")
        idx += 1
    if _is_wine_brand_task(text):
        lines.extend([
            f"{idx}. 做高端酒类品牌视觉，不要做普通电商模板。",
            f"{idx + 1}. 页面应包含 Hero、精选酒款、品牌故事、年份/产区信息、品鉴 CTA。",
            f"{idx + 2}. 视觉方向建议：深色高级、玻璃质感、细腻光影、克制动效、强产品视觉锚点。",
            f"{idx + 3}. 用数据库 UI 规则约束排版、间距、层级和质感。",
            f"{idx + 4}. 不要使用未经授权的真实酒类品牌商标或图片；可用占位图、渐变、SVG、CSS 视觉元素。",
        ])
        idx += 5
    if _contains_any(text, ("handoff", "agent handoff", "提示词", "交接")):
        lines.append(f"{idx}. 如果是 Agent Handoff 结果，优先展示目标 Agent、数据库 brief 状态、handoff 文件路径和提示词预览。")
        idx += 1
        lines.append(f"{idx}. 不要保存完整 prompt 到 task history。")
        idx += 1
    lines.append(f"{idx}. 不要新增 Agent 启动能力、终端启动能力或剪贴板/打开文件能力，除非用户明确要求。")
    return lines


def _acceptance_lines(
    actual_task: str,
    domains: list[str],
    *,
    target_project_kind: str,
) -> list[str]:
    text = _compact_inline(actual_task).lower()
    if str(target_project_kind or "").startswith("external"):
        lines = [
            "1. 输出内容能让用户看懂当前做了什么。",
            "2. 不修改小黄项目，所有项目改动只发生在目标项目路径内。",
            "3. 不提交 runtime/log/data 临时文件或 secret。",
            "4. 按目标项目已有脚本完成 lint/test/build 或等价验证。",
        ]
    else:
        lines = [
            "1. 相关功能可通过现有 Chat / confirm flow 触发。",
            "2. 输出内容能让用户看懂当前做了什么。",
            "3. 不破坏 existing readonly task / health report / task history。",
            "4. 不提交 runtime/log/data 临时文件。",
            "5. compileall、unittest、help、diff check 通过。",
        ]
    idx = len(lines) + 1
    if _contains_any(text, ("handoff", "agent handoff", "提示词", "交接")):
        lines.append(f"{idx}. 生成的 handoff prompt 中应明确区分“用户原始需求”和“实际工程任务”。")
        idx += 1
        lines.append(f"{idx}. handoff 不应诱导目标 Agent 继续生成提示词，除非用户明确只要提示词。")
        idx += 1
    if _contains_any(text, ("ui", "页面", "界面", "前端")) or "ui_design" in set(domains or []):
        lines.append(f"{idx}. 页面结构更清晰，可读性提升。")
        idx += 1
        lines.append(f"{idx}. 不破坏已有 section isolation 和 independent scroll containers。")
        idx += 1
    if _contains_any(text, ("数据库", "brief")) or "database" in set(domains or []):
        lines.append(f"{idx}. 数据库不可用时仍能安全降级。")
        idx += 1
        lines.append(f"{idx}. 不直接读取或写入 E:\\DataBase。")
    return lines


def _allowed_scope_lines(
    *,
    xiaohuang_project_root: str,
    target_project_path: str,
    target_project_kind: str,
    project_relation: str,
) -> list[str]:
    if str(target_project_kind or "").startswith("external"):
        lines = [
            "- 只修改目标项目路径内与任务直接相关的源码、测试、文档和任务记忆。",
        ]
        if project_relation == "unrelated_to_xiaohuang":
            lines.append(f"- 本任务和小黄项目无关，不要修改 {xiaohuang_project_root}。")
        if target_project_path and target_project_path != "未指定":
            lines.append(f"- 目标项目路径为 {target_project_path}；不要越界到其他目录。")
        else:
            lines.append("- 目标项目路径未指定时，不要执行修改；先要求用户确认路径。")
        return lines
    return ["- 只修改与任务直接相关的源码、测试、文档和任务记忆。"]


def _verification_lines(*, target_project_path: str, target_project_kind: str) -> list[str]:
    if target_project_kind == "xiaohuang":
        return [
            "```powershell",
            f"cd {target_project_path}",
            "$env:PYTHONPATH=\"E:\\Projects\\xiaohuang\\src\"",
            "$env:PYTHONUTF8=\"1\"",
            "$env:PYTHONIOENCODING=\"utf-8\"",
            "F:\\for_xiaohuang\\conda310\\python.exe -m compileall -q src scripts tests",
            "F:\\for_xiaohuang\\conda310\\python.exe -m unittest discover -s tests",
            "F:\\for_xiaohuang\\conda310\\python.exe scripts\\control_panel_web.py --help",
            "F:\\for_xiaohuang\\conda310\\python.exe scripts\\voice_overlay.py --help",
            "git diff --check",
            "git status --short",
            "```",
        ]
    if target_project_kind == "external_unspecified":
        return [
            "```text",
            "目标项目路径未指定：先向用户确认路径，再按目标项目技术栈选择验证命令。",
            "```",
        ]
    return [
        "```powershell",
        f"cd {target_project_path or '<目标项目路径>'}",
        "npm run lint",
        "npm run test",
        "npm run build",
        "git diff --check",
        "git status --short",
        "```",
        "如果目标项目没有上述脚本，请先读取 package.json，再运行该项目已有的等价验证命令。",
    ]


def _bullet_lines(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items] or ["- 先根据任务搜索相关源码和测试。"]


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term.lower() in text for term in terms)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _resolve_target_project_kind(request: AgentHandoffRequest) -> str:
    kind = str(request.target_project_kind or "auto")
    if kind != "auto":
        return kind
    relation = str(request.project_relation or "auto")
    if relation == "xiaohuang_project":
        return "xiaohuang"
    if request.target_project_path:
        return "external_existing"
    return "external_unspecified" if relation == "unrelated_to_xiaohuang" else "xiaohuang"


def _resolve_project_relation(request: AgentHandoffRequest, target_project_kind: str) -> str:
    relation = str(request.project_relation or "auto")
    if relation != "auto":
        return relation
    return "xiaohuang_project" if target_project_kind == "xiaohuang" else "unrelated_to_xiaohuang"


def _resolve_target_project_path(
    request: AgentHandoffRequest,
    xiaohuang_project_root: str,
    target_project_kind: str,
) -> str:
    if target_project_kind == "xiaohuang":
        return str(request.target_project_path or request.project_hint or xiaohuang_project_root)
    return str(request.target_project_path or request.project_hint or "未指定")


def _is_wine_brand_task(text: str) -> bool:
    return _contains_any(
        text,
        ("酒", "红酒", "葡萄酒", "wine", "品牌官网", "产品展示"),
    )
