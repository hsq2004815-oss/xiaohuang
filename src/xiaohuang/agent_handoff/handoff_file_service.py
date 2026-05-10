"""File persistence for Agent Handoff draft prompts."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

_SAFE_NAME_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff_-]+")


def get_handoff_dir(project_root: Path | str) -> Path:
    return Path(project_root).resolve() / "runtime" / "agent_handoffs"


def write_handoff_file(
    *,
    project_root: Path | str,
    target_agent: str,
    user_request: str,
    content: str,
    now: datetime | None = None,
) -> Path:
    out_dir = get_handoff_dir(project_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    slug = _slugify(user_request)
    target = _slugify(target_agent) or "generic"
    candidate = out_dir / f"{stamp}_{target}_{slug}.txt"
    path = _dedupe_path(candidate)
    path.write_text(str(content or ""), encoding="utf-8")
    return path


def relative_handoff_path(path: Path, project_root: Path | str) -> str:
    try:
        return path.resolve().relative_to(Path(project_root).resolve()).as_posix()
    except ValueError:
        return str(path)


def _dedupe_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for idx in range(2, 1000):
        candidate = path.with_name(f"{stem}-{idx}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"cannot allocate handoff file name near {path}")


def _slugify(value: str, limit: int = 48) -> str:
    text = str(value or "").strip().lower()
    text = _SAFE_NAME_RE.sub("-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-_")
    return (text[:limit].strip("-_") or "handoff")
