"""diagnostic_export/models.py — dataclasses for the diagnostic export capability."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class DiagnosticHistoryEntry:
    time: str
    op: str
    ok: bool | None
    detail: str


@dataclass(frozen=True)
class DiagnosticExportInput:
    exported_from: str = "control_panel_web"
    bridge_ready: bool = False
    status: dict = field(default_factory=dict)
    log_paths: dict = field(default_factory=dict)
    drawer: dict = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class DiagnosticExportResult:
    ok: bool
    path: str | None = None
    content: str | None = None
    message: str = ""
