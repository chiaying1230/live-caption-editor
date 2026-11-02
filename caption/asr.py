import os
import threading
from pathlib import Path


class WhisperEngine:
    backend = "whisper"
    label = "Whisper"
    def __init__(self):
        self.model = None
        self.lock = threading.Lock()
        self.name = os.getenv("ASR_MODEL", "base")
        self.device = os.getenv("ASR_DEVICE", "cpu")
        self.compute = os.getenv("ASR_COMPUTE_TYPE", "int8" if self.device == "cpu" else "float16")

    def load(self):
        with self.lock:
            if self.model is None:
                from faster_whisper import WhisperModel
                from faster_whisper.utils import download_model
                from huggingface_hub.errors import LocalEntryNotFoundError
                from opencc import OpenCC
                self.converter = OpenCC("s2twp")
                cache = str(Path(os.getenv("MODEL_DIR", ".cache/models")))
                model_path = self.name
                if not Path(model_path).is_dir():
                    try:
                        model_path = download_model(self.name, cache_dir=cache, local_files_only=True)
                        # An interrupted download can leave a snapshot directory
                        # without all required files. Complete it on the next start.
                        if not all((Path(model_path) / f).is_file() for f in ("model.bin", "config.json", "tokenizer.json")):
                            model_path = download_model(self.name, cache_dir=cache)
                    except LocalEntryNotFoundError:
                        model_path = download_model(self.name, cache_dir=cache)
                self.model = WhisperModel(model_path, device=self.device, compute_type=self.compute,
                                          cpu_threads=int(os.getenv("ASR_CPU_THREADS", "4")))

    def transcribe(self, audio):
        self.load()
        with self.lock:
            segments, _ = self.model.transcribe(
                audio, language="zh", task="transcribe", beam_size=1,
                condition_on_previous_text=False, temperature=0,
                vad_filter=True, vad_parameters={"min_silence_duration_ms": 400},
                initial_prompt="以下是繁體中文逐字稿，請使用繁體中文與標點符號。",
            )
            return self.converter.convert("".join(s.text for s in segments).strip())


def create_engine():
    backend = os.getenv("ASR_BACKEND", "whisper").lower()
    if backend == "funasr":
        from .funasr_engine import FunASREngine
        return FunASREngine()
    if backend == "whisper":
        return WhisperEngine()
    raise ValueError("ASR_BACKEND must be whisper or funasr")
