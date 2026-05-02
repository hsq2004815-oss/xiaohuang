from __future__ import annotations

import ctypes
import os
import sys
import uuid
from pathlib import Path
from typing import Callable


WarningFunc = Callable[[str], None]


def play_audio_file(audio_path: Path, *, warn: WarningFunc = print) -> bool:
    path = Path(audio_path)
    if not path.exists():
        warn(f"Warning: audio file not found: {path}")
        return False

    if sys.platform.startswith("win"):
        return _play_audio_mci(path, warn=warn)

    try:
        os.startfile(str(path))
        return True
    except Exception as exc:
        warn(f"Warning: failed to play audio {path}: {exc}")
        return False


def _play_audio_mci(path: Path, *, warn: WarningFunc) -> bool:
    alias = f"xiaohuang_tts_{uuid.uuid4().hex}"
    path_str = str(path)
    try:
        _mci_send(f'open "{path_str}" type mpegvideo alias {alias}')
        _mci_send(f"play {alias} wait")
        return True
    except Exception as exc:
        warn(f"Warning: TTS playback failed: {exc}")
        return False
    finally:
        try:
            _mci_send(f"close {alias}")
        except Exception:
            pass


def _mci_send(command: str) -> None:
    winmm = ctypes.WinDLL("winmm")
    buf = ctypes.create_unicode_buffer(1024)
    result = winmm.mciSendStringW(command, buf, len(buf), None)
    if result != 0:
        err_buf = ctypes.create_unicode_buffer(1024)
        winmm.mciGetErrorStringW(result, err_buf, len(err_buf))
        raise OSError(f"MCI error: {err_buf.value}")
