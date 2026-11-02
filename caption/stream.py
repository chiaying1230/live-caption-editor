"""Bounded utterance buffering, coalesced previews and an independent ASR worker."""
import asyncio
from collections import deque
from dataclasses import dataclass

import numpy as np

RATE = 16000
FRAME = 1600  # 100 ms; the browser sends exactly this many PCM16 samples.


@dataclass
class Job:
    segid: str
    audio: np.ndarray
    end: float
    final: bool


class AudioStream:
    def __init__(self, store, sid, engine, send, *, threshold=0.008, silence_frames=8, max_frames=120):
        self.store, self.sid, self.engine, self.send = store, sid, engine, send
        self.threshold, self.silence_frames, self.max_frames = threshold, silence_frames, max_frames
        self.offset = store.offset(sid)
        self.frames = 0
        self.pre = deque(maxlen=2)
        self.active = []
        self.segid = None
        self.quiet = 0
        self.finals = deque()
        self.preview = None
        self.wake = asyncio.Event()
        self.finishing = False
        self.failed = False
        self.last_preview = 0

    async def feed(self, data):
        if self.failed or self.finishing:
            raise ValueError("收音已停止。")
        if len(data) != FRAME * 2:
            raise ValueError("音訊格式錯誤：需要 16 kHz mono PCM16，每包 100 ms。")
        audio = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
        self.frames += 1
        speech = float(np.sqrt(np.mean(audio * audio))) >= self.threshold
        if self.segid is None:
            if not speech:
                self.pre.append(audio)
                return
            start = self.offset + (self.frames - 1 - len(self.pre)) / 10
            self.segid = self.store.begin(self.sid, start, self.offset + self.frames / 10)
            self.active = list(self.pre)
            self.pre.clear()
            self.quiet = 0
            self.last_preview = 0
        self.active.append(audio)
        self.quiet = 0 if speech else self.quiet + 1
        end = self.offset + self.frames / 10
        if self.quiet >= self.silence_frames or len(self.active) >= self.max_frames:
            await self._finalize(end)
        elif len(self.active) >= 12 and len(self.active) - self.last_preview >= 12:
            self.preview = Job(self.segid, np.concatenate(self.active), end, False)
            self.last_preview = len(self.active)
            self.wake.set()

    async def _finalize(self, end):
        # Queue overflow is explicit and ends capture, never silently drops audio.
        # Keep this last job too, so Stop can drain all accepted speech.
        self.finals.append(Job(self.segid, np.concatenate(self.active), end, True))
        if self.preview and self.preview.segid == self.segid:
            self.preview = None
        self.segid, self.active, self.quiet = None, [], 0
        self.wake.set()
        if len(self.finals) > 3:
            raise ValueError("辨識速度跟不上收音，已停止接收。正在處理已收到的音訊；可改用較小模型。")

    async def finish(self):
        if not self.finishing:
            self.finishing = True
            if self.segid is not None:
                # One extra final can be queued during shutdown; still bounded.
                try:
                    await self._finalize(self.offset + self.frames / 10)
                except ValueError:
                    pass
            self.wake.set()

    async def run(self):
        while True:
            await self.wake.wait()
            self.wake.clear()
            while self.finals or self.preview:
                job = self.finals.popleft() if self.finals else self.preview
                if job is self.preview:
                    self.preview = None
                try:
                    text = await asyncio.to_thread(self.engine.transcribe, job.audio)
                    row = self.store.apply_asr(self.sid, job.segid, text, job.end, job.final)
                    await self.send({"type": "segment", "segment": row})
                except Exception:
                    self.failed = True
                    # Keep provisional text in SQLite; never call an unsuccessful result committed.
                    await self.send({"type": "error", "message": "辨識失敗，暫定字幕已保留。請停止收音並查看伺服器視窗。"})
                    raise
            if self.finishing:
                return
