"""startup_diagnostics/models.py — StartupDiagnostic dataclass."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StartupDiagnostic:
    kind: str
    severity: str
    summary: str
    suggestion: str
    source_file: str | None = None
    matched_text: str | None = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "summary": self.summary,
            "suggestion": self.suggestion,
            "source_file": self.source_file,
        }
