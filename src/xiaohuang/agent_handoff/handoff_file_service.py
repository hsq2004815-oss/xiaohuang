"""File persistence for Agent Handoff draft prompts."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

_SAFE_NAME_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff_-]+")
_MAX_HANDOFF_READ_BYTES = 256 * 1024


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


def read_handoff_file(
    project_root: Path | str,
    relative_path: str,
    max_bytes: int = _MAX_HANDOFF_READ_BYTES,
) -> dict:
    raw_path = str(relative_path or "").strip()
    if not raw_path:
        return _read_result(False, "", "", 0, "missing handoff path")
    supplied = Path(raw_path)
    if supplied.is_absolute():
        return _read_result(False, "", "", 0, "handoff path is not allowed")
    if supplied.suffix.lower() != ".txt":
        return _read_result(False, "", "", 0, "handoff file must be .txt")

    root = Path(project_root).resolve()
    handoff_dir = get_handoff_dir(root).resolve()
    requested = (root / supplied).resolve()
    try:
        requested.relative_to(handoff_dir)
    except ValueError:
        return _read_result(False, "", "", 0, "handoff path is not allowed")
    if not requested.is_file():
        return _read_result(False, raw_path, "", 0, "handoff file not found")
    try:
        size = requested.stat().st_size
    except OSError:
        return _read_result(False, raw_path, "", 0, "handoff file not found")
    if size > max(0, int(max_bytes)):
        return _read_result(False, raw_path, "", size, "handoff file is too large")
    try:
        content = requested.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return _read_result(False, raw_path, "", size, "handoff file is not valid utf-8")
    except OSError:
        return _read_result(False, raw_path, "", size, "handoff file not found")
    return _read_result(True, relative_handoff_path(requested, root), content, size, "")


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


def _read_result(ok: bool, path: str, content: str, size: int, error: str) -> dict:
    return {
        "ok": bool(ok),
        "path": str(path or ""),
        "content": str(content or ""),
        "size": int(size or 0),
        "error": str(error or ""),
    }
