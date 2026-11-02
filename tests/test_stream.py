import asyncio
import numpy as np
import pytest

from caption.store import Store
from caption.stream import AudioStream

VOICE = (np.ones(1600, dtype="<i2") * 2000).tobytes()
SILENCE = bytes(3200)


class Engine:
    def transcribe(self, audio):
        return "這是繁體中文。"


def test_preview_final_stop_and_continuation(tmp_path):
    async def scenario():
        store = Store(tmp_path / "stream.db")
        sid = store.create_session("測試")["id"]
        events = []

        async def send(row):
            events.append(row)

        stream = AudioStream(store, sid, Engine(), send)
        worker = asyncio.create_task(stream.run())
        for _ in range(12):
            await stream.feed(VOICE)
        # Wait for an actual provisional event, not an arbitrary sleep.
        for _ in range(100):
            if events:
                break
            await asyncio.sleep(.01)
        assert events[0]["segment"]["status"] == "provisional"
        for _ in range(8):
            await stream.feed(SILENCE)
        await stream.feed(VOICE)  # A short final phrase must be flushed by Stop too.
        await stream.finish()
        await worker
        rows = store.segments(sid)
        assert len(rows) == 2
        assert all(r["status"] == "committed" for r in rows)
        assert rows[0]["end"] <= rows[1]["start"]
        resumed = AudioStream(store, sid, Engine(), send)
        assert resumed.offset == rows[-1]["end"]
        store.close()
    asyncio.run(scenario())


def test_bounded_overload_drains_accepted_jobs(tmp_path):
    async def scenario():
        store = Store(tmp_path / "overflow.db")
        sid = store.create_session("測試")["id"]
        async def send(row):
            pass
        stream = AudioStream(store, sid, Engine(), send, max_frames=2)
        with pytest.raises(ValueError, match="跟不上"):
            for _ in range(8):
                await stream.feed(VOICE)
        assert len(stream.finals) == 4
        await stream.finish()
        await stream.run()
        assert all(r["status"] == "committed" for r in store.segments(sid))
        store.close()
    asyncio.run(scenario())


def test_silence_does_not_create_segments_and_malformed_pcm_rejected(tmp_path):
    async def scenario():
        store = Store(tmp_path / "silent.db")
        sid = store.create_session("測試")["id"]
        stream = AudioStream(store, sid, Engine(), None)
        for _ in range(50):
            await stream.feed(SILENCE)
        assert store.segments(sid) == []
        with pytest.raises(ValueError, match="音訊格式"):
            await stream.feed(b"bad")
        store.close()
    asyncio.run(scenario())
