import tempfile
import unittest
from pathlib import Path

from xiaohuang.audio_capture_service import build_recording_path
from xiaohuang.config_service import load_config
from xiaohuang.stt_service import MissingDependencyError, SenseVoiceTranscriber
from xiaohuang.vad_service import FixedDurationVad


class ConfigServiceTests(unittest.TestCase):
    def test_load_config_reads_nested_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "xiaohuang.yaml"
            config_path.write_text(
                "audio:\n  sample_rate: 16000\n  channels: 1\nrecording:\n  duration_seconds: 5\n",
                encoding="utf-8",
            )

            config = load_config(config_path)

            self.assertEqual(config["audio"]["sample_rate"], 16000)
            self.assertEqual(config["audio"]["channels"], 1)
            self.assertEqual(config["recording"]["duration_seconds"], 5)


class AudioCaptureServiceTests(unittest.TestCase):
    def test_build_recording_path_uses_timestamp_and_wav_suffix(self):
        output_dir = Path("data") / "recordings"

        path = build_recording_path(output_dir, timestamp="20260430_120000")

        self.assertEqual(path, output_dir / "test_20260430_120000.wav")


class VadServiceTests(unittest.TestCase):
    def test_fixed_duration_vad_reports_configured_seconds(self):
        vad = FixedDurationVad(duration_seconds=5)

        self.assertEqual(vad.get_recording_duration_seconds(), 5)


class SttServiceTests(unittest.TestCase):
    def test_sensevoice_transcriber_reports_missing_funasr_cleanly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            wav_path = Path(temp_dir) / "sample.wav"
            wav_path.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
            transcriber = SenseVoiceTranscriber(model_name="iic/SenseVoiceSmall", funasr_module=None)

            with self.assertRaises(MissingDependencyError) as context:
                transcriber.transcribe(wav_path)

            self.assertIn("FunASR", str(context.exception))


if __name__ == "__main__":
    unittest.main()
