from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentCompletionReport:
    raw_text: str
    task_title: str = ""
    changed_files: list[str] = field(default_factory=list)
    implemented_items: list[str] = field(default_factory=list)
    safety_claims: list[str] = field(default_factory=list)
    test_claims: list[str] = field(default_factory=list)
    manual_acceptance: list[str] = field(default_factory=list)
    commit_hash: str = ""
    commit_message: str = ""
    agent_name: str = ""


@dataclass(frozen=True)
class VerificationSignal:
    name: str
    status: str
    source_text: str = ""


@dataclass(frozen=True)
class RiskSignal:
    level: str
    message: str
    source_text: str = ""


@dataclass(frozen=True)
class AgentCompletionReview:
    ok: bool
    verdict: str
    confidence: str
    title: str
    summary: str
    task_title: str
    commit_hash: str
    changed_files: list[str]
    verification_summary: str
    safety_summary: str
    risk_points: list[str]
    next_steps: list[str]
    safe_details_excerpt: str
    tags: list[str]
    error_message: str = ""
