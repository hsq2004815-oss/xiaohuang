from __future__ import annotations

import uuid


def generate_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:12]}"


def normalize_request_id(value: str | None) -> str:
    if value:
        return str(value)
    return generate_request_id()
