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

from .asr import create_engine
from .store import Store, export_transcript
from .stream import AudioStream
from .recording import AudioArchive, RecordingError

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


class GlossaryEntry(BaseModel):
    source: str = Field(min_length=1,max_length=100)
    target: str = Field(min_length=1,max_length=100)


class GlossaryInput(BaseModel):
    entries: list[GlossaryEntry] = Field(max_length=500)


class MemorySetting(BaseModel):
    enabled: bool


class RememberedTerm(MemorySetting):
    source: str = Field(min_length=1,max_length=100)


def same_origin(origin, host):
    if not origin:
        return True  # Local command-line clients do not send Origin.
    parsed = urlsplit(origin)
    return parsed.scheme in ("http", "https") and parsed.netloc == host


def create_app(db_path=None, engine=None):
    database = Path(db_path or Path(os.getenv("DATA_DIR", "data")) / "captions.sqlite3")
    store = Store(database)
    archive = AudioArchive(store, database.parent / 'recordings')
    engine = engine or create_engine()
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
                "backend": getattr(engine, "backend", "test"), "label": getattr(engine, "label", "Whisper"),
                "chunk_ms": getattr(engine, "chunk_ms", None),
                "preview_mode": getattr(engine, "preview_mode", None),
                "preview_ms": getattr(engine, "preview_frames", 12) * 100,
                "model_loaded": getattr(engine, "model", None) is not None, "busy": bool(recordings),
                "capture": next((s.stats() for s in recordings.values() if s is not None), None)}

    @app.get("/api/sessions")
    def sessions():
        return store.sessions()

    @app.get("/api/glossary")
    def glossary():
        return {"entries":store.glossary()}

    @app.put("/api/glossary")
    def save_glossary(body: GlossaryInput):
        sources = [entry.source for entry in body.entries]
        if len(set(sources)) != len(sources) or any(
            entry.source.strip()!=entry.source or entry.target.strip()!=entry.target or
            entry.source == entry.target or any(c in entry.source+entry.target for c in '\n\r\t')
            for entry in body.entries
        ):
            raise HTTPException(422,"錯詞不能重複；詞彙需去除頭尾空白，且不能相同或包含換行／Tab。")
        return {"entries":store.save_glossary(body.entries)}

    @app.get('/api/correction-memory')
    def correction_memory():
        return {'enabled':store.remember_enabled(),'terms':store.remembered_terms(),
                'history':store.correction_history()}

    @app.put('/api/correction-memory')
    def set_correction_memory(body: MemorySetting):
        store.set_remember_enabled(body.enabled)
        return {'enabled':store.remember_enabled()}

    @app.patch('/api/correction-memory/terms')
    def set_remembered_term(body: RememberedTerm):
        try:
            store.set_remembered_term(body.source,body.enabled)
        except KeyError:
            raise HTTPException(404,'找不到這筆已記住的詞語。')
        return {'terms':store.remembered_terms()}

    @app.get('/api/correction-memory/export')
    def export_correction_memory():
        result={'terms':store.remembered_terms(),'history':store.correction_history(limit=100000),
                'whole_segments_human_verified':False,'model_trained':False}
        return Response(json.dumps(result,ensure_ascii=False,indent=2),media_type='application/json',
            headers={'Content-Disposition':'attachment; filename="correction-memory.json"'})

    @app.post("/api/sessions", status_code=201)
    def new_session(body: SessionInput):
        return store.create_session(body.title.strip() or "未命名聽打")

    @app.get("/api/sessions/{sid}")
    def get_session(sid: str):
        return {"session": session_or_404(sid), "segments": store.segments(sid),
                "recording": sid in recordings, "recordings": store.audio_recordings(sid)}

    @app.get('/api/sessions/{sid}/recordings')
    def list_recordings(sid: str):
        session_or_404(sid)
        return {'recordings': store.audio_recordings(sid)}

    @app.get('/api/sessions/{sid}/recordings/{rid}/audio')
    def recording_audio(sid: str, rid: str, download: bool = False):
        session_or_404(sid)
        row = next((r for r in store.audio_recordings(sid) if r['id']==rid), None)
        if not row:
            raise HTTPException(404, '找不到這份錄音。')
        if row['status']=='recording':
            raise HTTPException(409, '錄音中，請停止收音後再回放或下載。')
        path = archive.path(row['id'])
        if not path.is_file():
            raise HTTPException(404, '錄音檔不存在，請確認本機備份。')
        return FileResponse(path, media_type='audio/wav', filename=f'recording-{rid}.wav',
                            content_disposition_type='attachment' if download else 'inline')

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
        result = export_transcript(session_or_404(sid), store.segments(sid), fmt, store.audio_recordings(sid))
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
        stream = wav = None
        normal_stop = False
        worker = receiver = None
        try:
            await send({"type": "loading", "message": "正在準備辨識模型；首次會下載，請稍候。"})
            await asyncio.to_thread(engine.load)
            stream = AudioStream(store, sid, engine, send,
                                 threshold=float(os.getenv("VOICE_THRESHOLD", "0.003")))
            wav = archive.start(sid, stream.offset)
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
                    wav.write(message['bytes'])
                    await stream.feed(message["bytes"])
                elif message.get("text"):
                    command = json.loads(message["text"])
                    if command == {"type": "stop"}:
                        normal_stop = True
                        break
                    config = AudioConfiguration.model_validate(command)
                    stream.threshold = config.threshold
                    await send({"type": "configured", "threshold": stream.threshold})
        except WebSocketDisconnect:
            connected = False
        except RecordingError:
            log.exception('Audio recording failed')
            await send({'type':'error', 'message':'錄音無法寫入，已停止收音。請確認磁碟空間及資料夾是否可寫入。'})
        except (ValueError, json.JSONDecodeError) as exc:
            await send({"type": "error", "message": str(exc)})
        except Exception:
            log.exception("ASR/capture failed")
            await send({"type": "error", "message": "模型或辨識發生錯誤。請查看伺服器視窗，檢查模型下載與安裝。"})
        finally:
            if receiver and not receiver.done():
                receiver.cancel()
            if wav:
                try:
                    wav.finish(interrupted=not normal_stop)
                except Exception:
                    log.exception('Audio recording finalization failed')
                    await send({'type':'error', 'message':'錄音保存未完整完成，請檢查本機磁碟與錄音檔。'})
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
