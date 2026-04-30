from __future__ import annotations

import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any


class MissingDependencyError(RuntimeError):
    pass


class ModelInitializationError(RuntimeError):
    pass


class TranscriptionError(RuntimeError):
    pass


class SenseVoiceTranscriber:
    def __init__(
        self,
        model_name: str = "iic/SenseVoiceSmall",
        language: str = "auto",
        use_itn: bool = True,
        funasr_module: Any | None = "auto",
        postprocess_func: Any | None = None,
    ) -> None:
        self.model_name = model_name
        self.language = language
        self.use_itn = use_itn
        self._funasr_module = funasr_module
        self._postprocess_func = postprocess_func
        self._model = None

    def transcribe(self, wav_path: str | Path) -> str:
        source = Path(wav_path)
        if not source.exists():
            raise FileNotFoundError(f"WAV file not found: {source}")

        model = self._get_model()
        try:
            result = model.generate(
                input=str(source),
                language=self.language,
                use_itn=self.use_itn,
                batch_size_s=60,
                merge_vad=True,
                merge_length_s=15,
            )
        except Exception as exc:
            raise TranscriptionError(
                f"FunASR generate failed: {exc}\n{format_runtime_diagnostics()}"
            ) from exc

        text = _extract_text(result)
        text = self._postprocess(text)
        if not text:
            raise TranscriptionError(f"FunASR returned no text. Raw result: {result!r}")
        return text

    def ensure_model_loaded(self) -> float:
        start = time.perf_counter()
        self._get_model()
        return time.perf_counter() - start

    def _get_model(self):
        if self._model is not None:
            return self._model

        funasr = self._load_funasr()
        try:
            self._model = funasr.AutoModel(
                model=self.model_name,
                trust_remote_code=True,
                remote_code="./model.py",
                vad_model="fsmn-vad",
                vad_kwargs={"max_single_segment_time": 30000},
                device="cpu",
                disable_update=True,
            )
        except Exception as exc:
            raise ModelInitializationError(
                f"FunASR model initialization failed: {exc}\n{format_runtime_diagnostics()}"
            ) from exc
        return self._model

    def _load_funasr(self):
        if self._funasr_module is None:
            raise MissingDependencyError(_funasr_install_message())
        if self._funasr_module != "auto":
            return self._funasr_module
        try:
            import funasr
        except ImportError as exc:
            raise MissingDependencyError(_funasr_install_message()) from exc
        return funasr

    def _postprocess(self, text: str) -> str:
        if self._postprocess_func is None:
            self._postprocess_func = _load_rich_transcription_postprocess()
        return str(self._postprocess_func(text)).strip()


def _extract_text(result: Any) -> str:
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, dict):
        return str(result.get("text", "")).strip()
    if isinstance(result, list):
        parts = [_extract_text(item) for item in result]
        return " ".join(part for part in parts if part).strip()
    return ""


def clean_command_text(text: str) -> str:
    cleaned = _remove_emoji(text).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"[。！？!?；;：:、，,]+$", "", cleaned)
    return cleaned.strip()


def _remove_emoji(text: str) -> str:
    return "".join(char for char in text if not _is_emoji(char))


def _is_emoji(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x1F300 <= codepoint <= 0x1FAFF
        or 0x2600 <= codepoint <= 0x27BF
        or 0xFE00 <= codepoint <= 0xFE0F
    )


def _load_rich_transcription_postprocess():
    try:
        from funasr.utils.postprocess_utils import rich_transcription_postprocess
    except ImportError as exc:
        raise MissingDependencyError(
            "FunASR rich_transcription_postprocess is unavailable. "
            "Verify that FunASR is installed in the active Python environment."
        ) from exc
    return rich_transcription_postprocess


def build_runtime_diagnostics() -> dict[str, str]:
    ffmpeg_path = shutil.which("ffmpeg")
    return {
        "python": sys.executable,
        "MODELSCOPE_CACHE": os.environ.get("MODELSCOPE_CACHE", ""),
        "HF_HOME": os.environ.get("HF_HOME", ""),
        "ffmpeg": ffmpeg_path or "not found",
    }


def format_runtime_diagnostics() -> str:
    diagnostics = build_runtime_diagnostics()
    lines = [
        "Runtime diagnostics:",
        f"- Python: {diagnostics['python']}",
        f"- MODELSCOPE_CACHE: {diagnostics['MODELSCOPE_CACHE'] or '(unset)'}",
        f"- HF_HOME: {diagnostics['HF_HOME'] or '(unset)'}",
        f"- ffmpeg: {diagnostics['ffmpeg']}",
    ]
    if diagnostics["ffmpeg"] == "not found":
        lines.append("- warning: ffmpeg not found, fallback to torchaudio for wav input")
    return "\n".join(lines)


def _funasr_install_message() -> str:
    return (
        "FunASR is not installed. For SenseVoiceSmall transcription, create/activate a "
        "project environment and install the STT stack, for example: "
        "`python -m pip install funasr modelscope torch torchaudio`. "
        "If Windows dependency resolution fails, use the official FunASR Windows SDK or "
        "temporarily validate recording only with `record_test.py`."
    )
