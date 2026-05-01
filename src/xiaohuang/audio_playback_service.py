from __future__ import annotations

import os
from pathlib import Path
from typing import Callable


WarningFunc = Callable[[str], None]


def play_audio_file(audio_path: Path, *, warn: WarningFunc = print) -> bool:
    path = Path(audio_path)
    try:
        if not path.exists():
            raise FileNotFoundError(str(path))
        os.startfile(str(path))  # type: ignore[attr-defined]
        return True
    except Exception as exc:
        warn(f"Warning: failed to play audio {path}: {exc}")
        return False
