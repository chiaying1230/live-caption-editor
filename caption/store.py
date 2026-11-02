"""SQLite is the authority for text and lock state, including late ASR results."""
import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS segments (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                start REAL NOT NULL, end REAL NOT NULL, text TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK(status IN ('provisional','committed','human_corrected')),
                locked INTEGER NOT NULL DEFAULT 0,
                revision INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS segment_session ON segments(session_id,start);
            CREATE TABLE IF NOT EXISTS glossary (
                source TEXT PRIMARY KEY, target TEXT NOT NULL
            );
        """)

    def create_session(self, title):
        row = {"id": uuid.uuid4().hex, "title": title, "created_at": now()}
        with self.lock, self.db:
            self.db.execute("INSERT INTO sessions VALUES (:id,:title,:created_at)", row)
        return row

    def sessions(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM sessions ORDER BY created_at DESC LIMIT 100")]

    def session(self, sid):
        with self.lock:
            row = self.db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
            return dict(row) if row else None

    def segments(self, sid):
        with self.lock:
            return [self._row(r) for r in self.db.execute(
                "SELECT * FROM segments WHERE session_id=? ORDER BY start,id", (sid,))]

    @staticmethod
    def _row(row):
        if row is None:
            return None
        result = dict(row)
        result["locked"] = bool(result["locked"])
        return result

    def get(self, sid, segid):
        with self.lock:
            return self._row(self.db.execute("SELECT * FROM segments WHERE session_id=? AND id=?", (sid, segid)).fetchone())

    def offset(self, sid):
        with self.lock:
            return float(self.db.execute("SELECT COALESCE(MAX(end),0) FROM segments WHERE session_id=?", (sid,)).fetchone()[0])

    def begin(self, sid, start, end):
        segid = uuid.uuid4().hex
        with self.lock, self.db:
            self.db.execute("INSERT INTO segments (id,session_id,start,end,status,updated_at) VALUES (?,?,?,?,'provisional',?)",
                            (segid, sid, start, end, now()))
        return segid

    def apply_asr(self, sid, segid, text, end, final=False):
        # Atomic predicate: even a stale ASR worker can never overwrite a human edit
        # or downgrade a committed segment back to provisional.
        with self.lock, self.db:
            terms = dict(self.db.execute("SELECT source,target FROM glossary"))
            if terms:
                # One pass, longest match first: replacements cannot cascade.
                pattern = "|".join(re.escape(source) for source in sorted(terms,key=len,reverse=True))
                text = re.sub(pattern, lambda match: terms[match.group()], text)
            self.db.execute("""UPDATE segments SET text=?,end=?,status=?,revision=revision+1,updated_at=?
                WHERE session_id=? AND id=? AND locked=0 AND status='provisional'""",
                (text, end, "committed" if final else "provisional", now(), sid, segid))
            return self.get(sid, segid)

    def glossary(self):
        with self.lock:
            return [dict(row) for row in self.db.execute("SELECT source,target FROM glossary ORDER BY source")]

    def save_glossary(self, entries):
        with self.lock, self.db:
            self.db.execute("DELETE FROM glossary")
            self.db.executemany("INSERT INTO glossary(source,target) VALUES (?,?)",
                                [(entry.source,entry.target) for entry in entries])
        return self.glossary()

    def correct(self, sid, segid, text, revision):
        with self.lock, self.db:
            row = self.get(sid, segid)
            if row is None:
                raise KeyError(segid)
            if row["status"] == "provisional":
                raise ValueError("暫定字幕尚未確認，請等候辨識完成。")
            if row["revision"] != revision:
                raise ValueError("這段文字已在其他畫面修改，請重新載入後再儲存。")
            self.db.execute("""UPDATE segments SET text=?,status='human_corrected',locked=1,
                revision=revision+1,updated_at=? WHERE id=?""", (text, now(), segid))
            return self.get(sid, segid)

    def close(self):
        self.db.close()


def timestamp(seconds, srt=False):
    ms = max(0, round(seconds * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}{',' if srt else '.'}{ms:03}"


def export_transcript(session, segments, fmt):
    if fmt == "json":
        return json.dumps({"schema_version": 1, "session": session, "segments": segments}, ensure_ascii=False, indent=2)
    if fmt == "srt":
        return "\n\n".join(f"{i}\n{timestamp(r['start'], True)} --> {timestamp(r['end'], True)}\n{r['text']}"
                           for i, r in enumerate((r for r in segments if r["status"] != "provisional" and r["text"]), 1)) + "\n"
    labels = {"provisional": "暫定／未確認", "committed": "AI 確認", "human_corrected": "人工校正／已鎖定"}
    lines = [session["title"], f"建立時間：{session['created_at']}", ""]
    lines += [f"[{timestamp(r['start'])} → {timestamp(r['end'])}] [{labels[r['status']]}]\n{r['text']}\n" for r in segments]
    return "\n".join(lines)
