"""Optional CPU ONNX recognizer with rolling utterance previews."""
import os
import threading
from pathlib import Path


class SenseVoiceEngine:
    backend = "sensevoice"
    label = "SenseVoice"
    name = "Small INT8 · 試用"
    device = "cpu"
    preview_frames = 24
    max_frames = 80

    def __init__(self, model=None, converter=None):
        self.model = model
        self.converter = converter
        self.lock = threading.Lock()

    def load(self):
        with self.lock:
            if self.model is not None:
                return
            try:
                import sherpa_onnx
                from huggingface_hub import snapshot_download
                from opencc import OpenCC
            except ImportError as exc:
                raise RuntimeError("SenseVoice 環境尚未安裝，請使用 start-sensevoice.cmd。") from exc
            path = Path(os.getenv("SENSEVOICE_MODEL_DIR", ".cache/asr-candidates/sensevoice"))
            if not all((path / file).is_file() for file in ("model.int8.onnx", "tokens.txt")):
                snapshot_download(
                    "csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
                    revision="2365baeacb507f821a0c8120fcee3d484dba7a07",
                    local_dir=path,
                    allow_patterns=["model.int8.onnx", "tokens.txt", "LICENSE", "README.md"],
                    max_workers=2,
                )
            model = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(path / "model.int8.onnx"), tokens=str(path / "tokens.txt"),
                language="zh", use_itn=True,
                num_threads=int(os.getenv("ASR_CPU_THREADS", "4")),
            )
            # Character conversion preserves the words the model recognized.
            self.converter = OpenCC("s2tw")
            self.model = model

    def new_session(self):
        return SenseVoiceSession(self)


class SenseVoiceSession:
    def __init__(self, engine):
        self.engine = engine

    def recognize(self, segid, audio, final):
        self.engine.load()
        with self.engine.lock:
            stream = self.engine.model.create_stream()
            stream.accept_waveform(16000, audio)
            self.engine.model.decode_stream(stream)
            text = stream.result.text.strip()
            if not final:
                text = text.rstrip('。！？!?，,；;：:、')
            return self.engine.converter.convert(text)
