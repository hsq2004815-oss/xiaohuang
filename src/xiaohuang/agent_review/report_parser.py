from __future__ import annotations

import re

from xiaohuang.agent_review.models import AgentCompletionReport

_COMMIT_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
_COMMIT_MESSAGE_RE = re.compile(
    r"\b(?:feat|fix|docs|test|tests|refactor|chore|style|perf|build|ci|revert)(?:\([^)]+\))?!?:\s+.+",
    re.IGNORECASE,
)
_PATH_RE = re.compile(
    r"(?<![\w:])("
    r"(?:\.github|\.codex|src|frontend|tests|docs|scripts|runtime|data|logs)"
    r"(?:/[A-Za-z0-9_.@()+-]+)+"
    r"|(?:TASK_MEMORY|AGENTS|README)(?:\.[A-Za-z0-9_.-]+)?"
    r"|[A-Za-z0-9_.@()+-]+\.(?:py|js|css|html|md|json|txt|toml|yml|yaml)"
    r")(?![\w])"
)

_SECTION_ALIASES = {
    "changed_files": (
        "改了哪些文件", "修改文件", "变更文件", "changed files", "files changed", "files",
    ),
    "implemented_items": (
        "实现了什么", "实现内容", "核心实现", "修复内容", "implemented", "implementation", "changes",
    ),
    "safety_claims": (
        "安全边界", "安全声明", "safety", "security boundary", "guardrails",
    ),
    "test_claims": (
        "测试覆盖", "验证结果", "测试结果", "verification", "tests", "test coverage",
    ),
    "manual_acceptance": (
        "人工验收", "手动验收", "manual acceptance", "manual qa", "manual test",
    ),
    "commit": (
        "最新提交", "提交", "commit", "commit hash", "latest commit",
    ),
}

_SECTION_ORDER = tuple(_SECTION_ALIASES)
_AGENT_NAMES = (
    ("claude code", "Claude Code"),
    ("opencode", "opencode"),
    ("openclaw", "OpenClaw"),
    ("codex", "Codex"),
)


def is_completion_report(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    lower = value.lower()
    compact = _compact(value)
    starts_like_done = bool(re.match(r"^(完成|已完成|done|completed)\s*[:：]", lower, re.IGNORECASE))
    has_changed_and_verification = (
        ("改了哪些文件" in compact or "changedfiles" in compact)
        and ("验证结果" in compact or "verification" in lower or "unittest" in lower or "compileall" in lower)
    )
    has_commit_context = bool(_COMMIT_RE.search(value)) and (
        "commit" in lower or "最新提交" in value or "git diff" in lower or "unittest" in lower
    )
    section_hits = sum(1 for aliases in _SECTION_ALIASES.values() if _contains_alias(value, aliases))
    return (starts_like_done and (has_commit_context or section_hits >= 2)) or (
        has_changed_and_verification and has_commit_context
    )


def parse_completion_report(text: str) -> AgentCompletionReport:
    raw_text = str(text or "")
    lines = [line.rstrip() for line in raw_text.splitlines()]
    sections = _split_sections(lines)
    changed_files = _extract_changed_files(sections.get("changed_files", []))
    test_claims = _clean_items(sections.get("test_claims", []))
    # Some reports put verification lines in separate "verification" wording that maps to test_claims.
    implemented_items = _clean_items(sections.get("implemented_items", []))
    safety_claims = _clean_items(sections.get("safety_claims", []))
    manual_acceptance = _clean_items(sections.get("manual_acceptance", []))
    commit_lines = sections.get("commit", [])
    commit_hash = _extract_commit_hash(commit_lines) or _extract_commit_hash(lines)
    commit_message = _extract_commit_message(lines, commit_hash)

    return AgentCompletionReport(
        raw_text=raw_text,
        task_title=_extract_task_title(lines),
        changed_files=changed_files,
        implemented_items=implemented_items,
        safety_claims=safety_claims,
        test_claims=test_claims,
        manual_acceptance=manual_acceptance,
        commit_hash=commit_hash,
        commit_message=commit_message,
        agent_name=_detect_agent_name(raw_text),
    )


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {name: [] for name in _SECTION_ORDER}
    current = ""
    for line in lines:
        heading = _section_name(line)
        if heading:
            current = heading
            continue
        if current:
            sections[current].append(line)
    return sections


def _section_name(line: str) -> str:
    stripped = str(line or "").strip()
    if not stripped:
        return ""
    if re.match(r"^[\-\*\u2022]\s+", stripped):
        return ""
    normalized = re.sub(r"^[#\-\s>*]+", "", stripped)
    normalized = re.sub(r"^[一二三四五六七八九十\d]+[、.)．]\s*", "", normalized)
    normalized = normalized.rstrip(":：").strip()
    normalized_lower = normalized.lower()
    compact = _compact(normalized)
    for name, aliases in _SECTION_ALIASES.items():
        for alias in aliases:
            alias_lower = alias.lower()
            if normalized_lower == alias_lower or alias_lower in normalized_lower:
                return name
            if _compact(alias) in compact:
                return name
    return ""


def _extract_task_title(lines: list[str]) -> str:
    for line in lines:
        stripped = str(line or "").strip()
        if not stripped:
            continue
        match = re.match(r"^(?:完成|已完成|done|completed)\s*[:：]\s*(.+)$", stripped, re.IGNORECASE)
        if match:
            return _clean_inline(match.group(1))[:120]
        return _clean_inline(stripped)[:120]
    return ""


def _extract_changed_files(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []
    for line in lines:
        for match in _PATH_RE.findall(line.replace("\\", "/")):
            path = _clean_path(match)
            if not _looks_like_project_path(path):
                continue
            key = path.lower()
            if key not in seen:
                seen.add(key)
                paths.append(path)
    return paths


def _looks_like_project_path(path: str) -> bool:
    if not path or "://" in path:
        return False
    if path.startswith(("-", "/")):
        return False
    if "/" in path:
        root = path.split("/", 1)[0]
        return root in {"src", "frontend", "tests", "docs", "scripts", "runtime", "data", "logs", ".github", ".codex"}
    return path in {"TASK_MEMORY.md", "AGENTS.md", "README.md"} or bool(re.search(r"\.(py|js|css|html|md|json|txt|toml|ya?ml)$", path))


def _clean_path(path: str) -> str:
    value = str(path or "").strip().replace("\\", "/")
    return value.strip("`'\"，,。；;：:（）()[]{}<>")


def _clean_items(lines: list[str]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for line in lines:
        item = _clean_inline(line)
        if not item:
            continue
        key = item.lower()
        if key not in seen:
            seen.add(key)
            items.append(item[:180])
    return items


def _clean_inline(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^[\-\*\u2022]\s*", "", value)
    value = re.sub(r"^\d+[.)、]\s*", "", value)
    return value.strip()


def _extract_commit_hash(lines: list[str]) -> str:
    joined = "\n".join(lines)
    matches = list(_COMMIT_RE.finditer(joined))
    if not matches:
        return ""
    for match in matches:
        start = max(0, match.start() - 80)
        end = min(len(joined), match.end() + 80)
        context = joined[start:end].lower()
        if "commit" in context or "提交" in context:
            return match.group(0)
    return matches[0].group(0)


def _extract_commit_message(lines: list[str], commit_hash: str) -> str:
    if not commit_hash:
        return ""
    for index, line in enumerate(lines):
        if commit_hash.lower() not in line.lower():
            continue
        same_line = _clean_inline(line.replace(commit_hash, ""))
        msg_match = _COMMIT_MESSAGE_RE.search(same_line)
        if msg_match:
            return msg_match.group(0)[:160]
        for follow in lines[index + 1:index + 4]:
            follow_clean = _clean_inline(follow)
            msg_match = _COMMIT_MESSAGE_RE.search(follow_clean)
            if msg_match:
                return msg_match.group(0)[:160]
            if follow_clean and not _COMMIT_RE.search(follow_clean):
                return follow_clean[:160]
    for line in lines:
        msg_match = _COMMIT_MESSAGE_RE.search(_clean_inline(line))
        if msg_match:
            return msg_match.group(0)[:160]
    return ""


def _detect_agent_name(text: str) -> str:
    lower = str(text or "").lower()
    for needle, name in _AGENT_NAMES:
        if needle in lower:
            return name
    return ""


def _contains_alias(text: str, aliases: tuple[str, ...]) -> bool:
    lower = str(text or "").lower()
    compact = _compact(text)
    return any(alias.lower() in lower or _compact(alias) in compact for alias in aliases)


def _compact(text: str) -> str:
    return "".join(str(text or "").lower().split())
