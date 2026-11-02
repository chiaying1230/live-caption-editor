"""Local Paraformer streaming previews and a separate sentence-final pass.

Imports are lazy so the default Whisper environment does not need PyTorch.
Every capture owns a recognizer cache; model weights are shared and serialized.
"""
import os
import threading
from pathlib import Path

import numpy as np


class FunASREngine:
    name = "Paraformer 2pass"
    label = "FunASR"
    backend = "funasr"
    device = "cpu"
    max_frames = 200

    def __init__(self, online=None, offline=None, converter=None, *, chunk_ms=None, preview_mode=None):
        self.preview_mode = preview_mode or os.getenv("FUNASR_PREVIEW_MODE", "streaming")
        if self.preview_mode not in ("streaming", "context"):
            raise ValueError("FUNASR_PREVIEW_MODE must be streaming or context")
        self.chunk_ms = int(chunk_ms or os.getenv("FUNASR_CHUNK_MS", "1200"))
        if self.chunk_ms not in (600, 1200, 1800):
            raise ValueError("FUNASR_CHUNK_MS must be 600, 1200 or 1800")
        self.preview_frames = self.chunk_ms // 100
        if self.preview_mode == "context":
            self.name = "Paraformer 連續校正"
            self.preview_frames = 15
            self.max_frames = 120
        self.model = online
        self.offline = offline
        self.converter = converter
        self.punctuation = None
        self.lock = threading.Lock()

    def load(self):
        with self.lock:
            if self.model is not None and self.offline is not None:
                return
            try:
                import torch
                from funasr import AutoModel
                from huggingface_hub import snapshot_download
                from opencc import OpenCC
            except ImportError as exc:
                raise RuntimeError("FunASR 環境尚未安裝完整，請使用 start-funasr.cmd。") from exc
            torch.set_num_threads(int(os.getenv("ASR_CPU_THREADS", "4")))
            root = Path(os.getenv("FUNASR_MODEL_DIR", ".cache/funasr"))
            paths = {}
            for kind, repo, revision, required in (
                ("streaming", "funasr/paraformer-zh-streaming", "apache-2.0-20260804", ("model.pt", "config.yaml", "am.mvn", "tokens.json")),
                ("offline", "funasr/paraformer-zh", "d7811ee3ac581fbcfdeb37c98c6ba674028433dc", ("model.pt", "config.yaml", "am.mvn", "tokens.json")),
                ("punctuation", "funasr/ct-punc", "d0e55e2b8722a78b63705ff443d09c4f86e5d750", ("model.pt", "config.yaml", "tokens.json")),
            ):
                if kind == "streaming" and self.preview_mode == "context":
                    continue
                path = root / kind
                if not all((path / f).is_file() for f in required):
                    snapshot_download(repo, revision=revision, local_dir=path,
                                      allow_patterns=["*.json", "*.yaml", "*.mvn", "*.pkl", "model.pt", "seg_dict", "LICENSE", "README.md"],
                                      max_workers=2)
                paths[kind] = str(path.resolve())
            options = dict(device="cpu", ncpu=int(os.getenv("ASR_CPU_THREADS", "4")),
                           disable_update=True, disable_pbar=True, trust_remote_code=False)
            online = AutoModel(model=paths["streaming"], **options) if "streaming" in paths else None
            offline = AutoModel(model=paths["offline"], **options)
            punctuation = AutoModel(model=paths["punctuation"], **options)
            # Publish only a complete two-pass engine; partial load failures are retryable.
            self.converter = OpenCC("s2twp")
            self.model, self.offline = online or offline, offline
            self.punctuation = punctuation

    def new_session(self):
        if self.preview_mode == "context":
            return ContextParaformerSession(self)
        return ParaformerSession(self)


class ContextParaformerSession:
    """Re-evaluate the current utterance for each provisional snapshot.

    This is rolling offline recognition, not native token streaming. Keeping
    context lets later audio fix earlier guesses without touching locked text.
    """
    def __init__(self, engine):
        self.engine = engine

    def recognize(self, segid, audio, final):
        self.engine.load()
        with self.engine.lock:
            text = result_text(self.engine.offline.generate(input=audio, disable_pbar=True))
            if text and self.engine.punctuation is not None:
                text = result_text(self.engine.punctuation.generate(input=text, disable_pbar=True))
            if not final:
                text = text.rstrip('。！？!?，,；;：:、')
            return self.engine.converter.convert(text)


def result_text(result):
    if not isinstance(result, list) or any(not isinstance(r, dict) or not isinstance(r.get("text", ""), str) for r in result):
        raise RuntimeError("FunASR 回傳了無法讀取的辨識結果。")
    return "".join(r.get("text", "") for r in result).strip()


class ParaformerSession:
    def __init__(self, engine):
        self.engine = engine
        self.stride = engine.chunk_ms * 16
        self.chunk_size = [0, engine.chunk_ms // 60, 5]
        self.reset()

    def reset(self):
        self.segid = None
        self.cache = {}
        self.consumed = 0
        self.text = ""

    def recognize(self, segid, audio, final, on_update=None):
        self.engine.load()
        with self.engine.lock:
            if final:
                # The offline model re-evaluates the entire utterance. It does not
                # append to provisional text and never writes directly to storage.
                result = self.engine.offline.generate(input=audio, disable_pbar=True)
                text = result_text(result)
                if text and self.engine.punctuation is not None:
                    text = result_text(self.engine.punctuation.generate(input=text, disable_pbar=True))
                if self.segid == segid:
                    self.reset()
                return self.engine.converter.convert(text)
            if self.segid != segid:
                self.reset()
                self.segid = segid
            # Snapshots can be coalesced by the worker. Feed every unseen sample
            # exactly once; skip nothing when an intermediate preview is replaced.
            while len(audio) - self.consumed >= self.stride:
                chunk = audio[self.consumed:self.consumed+self.stride]
                result = self.engine.model.generate(
                    input=chunk, cache=self.cache, is_final=False,
                    chunk_size=self.chunk_size, encoder_chunk_look_back=4,
                    decoder_chunk_look_back=1, disable_pbar=True,
                )
                self.text += result_text(result)
                self.consumed += self.stride
                # Publish each completed chunk, including chunks caught up from a
                # coalesced snapshot, instead of withholding them until the end.
                if on_update is not None and self.text:
                    on_update(self._display_text(), self.consumed)
            return self._display_text()

    def _display_text(self):
        text = self.text
        if text and self.engine.punctuation is not None:
            # Re-punctuate the provisional sentence; it may change until committed.
            if getattr(self, "punctuation_source", None) != text:
                self.punctuation_source = text
                self.punctuated = result_text(self.engine.punctuation.generate(input=text, disable_pbar=True))
            text = self.punctuated
        # The current chunk's end is not necessarily a sentence boundary.
        return self.engine.converter.convert(text.rstrip('。！？!?，,；;：:、'))

    supports_updates = True
