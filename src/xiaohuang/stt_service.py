from __future__ import annotations

from pathlib import Path
from typing import Any


class MissingDependencyError(RuntimeError):
    pass


class TranscriptionError(RuntimeError):
    pass


class SenseVoiceTranscriber:
    def __init__(
        self,
        model_name: str = "iic/SenseVoiceSmall",
        language: str = "zh",
        use_itn: bool = True,
        funasr_module: Any | None = "auto",
    ) -> None:
        self.model_name = model_name
        self.language = language
        self.use_itn = use_itn
        self._funasr_module = funasr_module
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
            )
        except Exception as exc:
            raise TranscriptionError(f"FunASR transcription failed: {exc}") from exc

        text = _extract_text(result)
        if not text:
            raise TranscriptionError(f"FunASR returned no text. Raw result: {result!r}")
        return text

    def _get_model(self):
        if self._model is not None:
            return self._model

        funasr = self._load_funasr()
        self._model = funasr.AutoModel(
            model=self.model_name,
            trust_remote_code=True,
        )
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


def _extract_text(result: Any) -> str:
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, dict):
        return str(result.get("text", "")).strip()
    if isinstance(result, list):
        parts = [_extract_text(item) for item in result]
        return " ".join(part for part in parts if part).strip()
    return ""


def _funasr_install_message() -> str:
    return (
        "FunASR is not installed. For SenseVoiceSmall transcription, create/activate a "
        "project environment and install the STT stack, for example: "
        "`python -m pip install funasr modelscope torch torchaudio`. "
        "If Windows dependency resolution fails, use the official FunASR Windows SDK or "
        "temporarily validate recording only with `record_test.py`."
    )
