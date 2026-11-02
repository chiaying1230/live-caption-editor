import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .asr import WhisperEngine
from .store import Store, export_transcript
from .stream import AudioStream

log = logging.getLogger("uvicorn.error")
STATIC = Path(__file__).parent / "static"


class SessionInput(BaseModel):
    title: str = Field(default="未命名聽打", min_length=1, max_length=120)


class Correction(BaseModel):
    text: str = Field(max_length=20000)
    revision: int = Field(ge=0)


class AudioConfiguration(BaseModel):
    type: Literal["configure"]
    threshold: float = Field(ge=0.0005, le=0.1, allow_inf_nan=False)


def same_origin(origin, host):
    if not origin:
        return True  # Local command-line clients do not send Origin.
    parsed = urlsplit(origin)
    return parsed.scheme in ("http", "https") and parsed.netloc == host


def create_app(db_path=None, engine=None):
    store = Store(db_path or Path(os.getenv("DATA_DIR", "data")) / "captions.sqlite3")
    engine = engine or WhisperEngine()
    recordings = {}

    @asynccontextmanager
    async def lifespan(app):
        yield
        store.close()

    app = FastAPI(title="即時聽打工作台", lifespan=lifespan)
    app.state.store = store
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_origin(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS") and not same_origin(request.headers.get("origin"), request.headers.get("host")):
            return Response("Origin denied", status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def session_or_404(sid):
        session = store.session(sid)
        if not session:
            raise HTTPException(404, "找不到這場聽打。")
        return session

    @app.get("/api/health")
    def health():
        return {"ok": True, "model": getattr(engine, "name", "test"), "device": getattr(engine, "device", "test"),
                "model_loaded": getattr(engine, "model", None) is not None, "busy": bool(recordings),
                "capture": next((s.stats() for s in recordings.values() if s is not None), None)}

    @app.get("/api/sessions")
    def sessions():
        return store.sessions()

    @app.post("/api/sessions", status_code=201)
    def new_session(body: SessionInput):
        return store.create_session(body.title.strip() or "未命名聽打")

    @app.get("/api/sessions/{sid}")
    def get_session(sid: str):
        return {"session": session_or_404(sid), "segments": store.segments(sid), "recording": sid in recordings}

    @app.patch("/api/sessions/{sid}/segments/{segid}")
    def correct(sid: str, segid: str, body: Correction):
        session_or_404(sid)
        try:
            return store.correct(sid, segid, body.text, body.revision)
        except KeyError:
            raise HTTPException(404, "找不到這段字幕。")
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.get("/api/sessions/{sid}/export/{fmt}")
    def export(sid: str, fmt: str):
        if fmt not in ("txt", "json", "srt"):
            raise HTTPException(404, "支援 TXT、JSON 與 SRT。")
        result = export_transcript(session_or_404(sid), store.segments(sid), fmt)
        media = "application/json" if fmt == "json" else "text/plain"
        # UTF-8 BOM makes Chinese TXT straightforward in Windows Notepad/Excel.
        content = ("\ufeff" + result) if fmt == "txt" else result
        return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="transcript-{sid[:8]}.{fmt}"'})

    @app.websocket("/api/sessions/{sid}/audio")
    async def audio(ws: WebSocket, sid: str):
        if not same_origin(ws.headers.get("origin"), ws.headers.get("host")):
            await ws.close(code=1008)
            return
        await ws.accept()
        connected = True

        async def send(message):
            nonlocal connected
            if connected:
                try:
                    await ws.send_json(message)
                except (WebSocketDisconnect, RuntimeError, OSError):
                    connected = False

        if not store.session(sid) or recordings:
            await send({"type": "error", "message": "找不到聽打，或已有收音正在處理。請等待停止完成。"})
            await ws.close(code=1008)
            return
        recordings[sid] = None  # Reserve before the first await; one capture per server.
        stream = None
        worker = receiver = None
        try:
            await send({"type": "loading", "message": "正在準備辨識模型；首次會下載，請稍候。"})
            await asyncio.to_thread(engine.load)
            stream = AudioStream(store, sid, engine, send,
                                 threshold=float(os.getenv("VOICE_THRESHOLD", "0.003")))
            recordings[sid] = stream
            worker = asyncio.create_task(stream.run())
            await send({"type": "ready", "offset": stream.offset, "threshold": stream.threshold})
            while connected:
                receiver = asyncio.create_task(ws.receive())
                done, _ = await asyncio.wait([receiver, worker], return_when=asyncio.FIRST_COMPLETED)
                if worker in done:
                    worker.result()  # Surface recognition failure and release capture.
                    break
                message = receiver.result()
                receiver = None
                if message["type"] == "websocket.disconnect":
                    connected = False
                    break
                if message.get("bytes") is not None:
                    await stream.feed(message["bytes"])
                elif message.get("text"):
                    command = json.loads(message["text"])
                    if command == {"type": "stop"}:
                        break
                    config = AudioConfiguration.model_validate(command)
                    stream.threshold = config.threshold
                    await send({"type": "configured", "threshold": stream.threshold})
        except WebSocketDisconnect:
            connected = False
        except (ValueError, json.JSONDecodeError) as exc:
            await send({"type": "error", "message": str(exc)})
        except Exception:
            log.exception("ASR/capture failed")
            await send({"type": "error", "message": "模型或辨識發生錯誤。請查看伺服器視窗，檢查模型下載與安裝。"})
        finally:
            if receiver and not receiver.done():
                receiver.cancel()
            try:
                if stream:
                    await stream.finish()
                if worker:
                    await worker
            except Exception:
                log.exception("ASR worker failed; provisional text retained")
            recordings.pop(sid, None)
            await send({"type": "stopped"})
            if connected:
                await ws.close()

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
