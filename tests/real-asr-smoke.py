"""Optional real-model transport check. Uses a WAV fixture, never a microphone."""
import asyncio
import json
import os

import httpx
import numpy as np
from faster_whisper.audio import decode_audio
from websockets.asyncio.client import connect


async def main():
    base = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8001")
    audio = decode_audio(os.getenv("SMOKE_AUDIO_PATH", "work/zh.wav"))
    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        sid = (await client.post("/api/sessions", json={"title":"公開音訊收音回歸測試"})).json()["id"]
        events = []
        async with connect(base.replace("http", "ws", 1) + f"/api/sessions/{sid}/audio") as ws:
            assert json.loads(await ws.recv())["type"] == "loading"
            assert json.loads(await asyncio.wait_for(ws.recv(), 120))["type"] == "ready"

            async def receive():
                async for message in ws:
                    event = json.loads(message)
                    events.append(event)
                    if event["type"] == "stopped":
                        return

            receiver = asyncio.create_task(receive())
            # Give the server the exact same PCM frames as the AudioWorklet.
            for offset in range(0, len(audio), 1600):
                frame = np.zeros(1600, np.float32)
                samples = audio[offset:offset+1600]
                frame[:len(samples)] = samples
                await ws.send((np.clip(frame, -1, 1) * 32767).astype("<i2").tobytes())
                await asyncio.sleep(.1)
            health = (await client.get("/api/health")).json()
            assert health["capture"]["received_seconds"] >= 4
            assert health["capture"]["speech_frames"] > 0
            await ws.send(json.dumps({"type":"stop"}))
            await asyncio.wait_for(receiver, 120)
        rows = (await client.get(f"/api/sessions/{sid}")).json()["segments"]
        assert any(e["type"] == "audio" for e in events)
        assert any(e["type"] == "recognizing" for e in events)
        assert any(e["type"] == "segment" and not e["segment"]["text"] for e in events)
        assert any(e["type"] == "segment" and e["segment"]["text"] for e in events)
        assert rows and all(r["status"] == "committed" for r in rows)
        assert any(r["text"] for r in rows)
        print(json.dumps({"result":"PASS", "events":len(events), "segments":len(rows),
                          "text":"".join(r["text"] for r in rows)}, ensure_ascii=True))


asyncio.run(main())
