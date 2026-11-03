"""SQLite is the authority for text and lock state, including late ASR results."""
import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .corrections import term_changes


def now():
    return datetime.now(timezone.utc).isoformat()


def replace_terms(text, terms):
    if not terms:
        return text
    pattern='|'.join(re.escape(source) for source in sorted(terms,key=len,reverse=True))
    return re.sub(pattern,lambda match:terms[match.group()],text)


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
            CREATE TABLE IF NOT EXISTS audio_recordings (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                start REAL NOT NULL, samples INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('recording','complete','interrupted'))
            );
            CREATE TABLE IF NOT EXISTS correction_history (
                segment_id TEXT PRIMARY KEY REFERENCES segments(id),
                session_id TEXT NOT NULL REFERENCES sessions(id),
                original_text TEXT NOT NULL, corrected_text TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS asr_baselines (
                segment_id TEXT PRIMARY KEY REFERENCES segments(id), text TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS correction_terms (
                segment_id TEXT NOT NULL REFERENCES segments(id),
                source TEXT NOT NULL, target TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(segment_id,source,target)
            );
            CREATE TABLE IF NOT EXISTS disabled_correction_terms (source TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
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
            return float(self.db.execute("""SELECT COALESCE(MAX(end),0) FROM (
                SELECT end FROM segments WHERE session_id=? UNION ALL
                SELECT start + samples / 16000.0 FROM audio_recordings WHERE session_id=?
            )""", (sid,sid)).fetchone()[0])

    def begin_recording(self, sid, start):
        row = dict(id=uuid.uuid4().hex, session_id=sid, start=start, samples=0,
                   created_at=now(), status='recording')
        with self.lock, self.db:
            self.db.execute("""INSERT INTO audio_recordings
                (id,session_id,start,samples,created_at,status)
                VALUES (:id,:session_id,:start,:samples,:created_at,:status)""", row)
        return row

    def update_recording(self, rid, samples, status='recording'):
        with self.lock, self.db:
            self.db.execute('UPDATE audio_recordings SET samples=?,status=? WHERE id=?', (samples,status,rid))

    def discard_recording(self, rid):
        with self.lock, self.db:
            self.db.execute('DELETE FROM audio_recordings WHERE id=?', (rid,))

    def audio_recordings(self, sid=None, *, unfinished=False):
        query = 'SELECT * FROM audio_recordings'
        params = ()
        if unfinished:
            query += " WHERE status='recording'"
        elif sid is not None:
            query += ' WHERE session_id=?'
            params = (sid,)
        with self.lock:
            rows = [dict(row) for row in self.db.execute(query+' ORDER BY created_at,id', params)]
        for row in rows:
            row['duration'] = row['samples'] / 16000
            row['end'] = row['start'] + row['duration']
        return rows

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
            terms = {r['source']:r['target'] for r in self.remembered_terms() if r['active']}
            manual=dict(self.db.execute("SELECT source,target FROM glossary"))
            baseline=replace_terms(text,manual)
            terms.update(manual)
            text=replace_terms(text,terms)  # One pass, longest first; never cascade.
            current=self.get(sid,segid)
            if current and current['status']=='provisional' and not current['locked']:
                self.db.execute('INSERT OR REPLACE INTO asr_baselines VALUES (?,?)',(segid,baseline))
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

    def remember_enabled(self):
        with self.lock:
            row=self.db.execute("SELECT value FROM settings WHERE key='remember_corrections'").fetchone()
            return not row or row[0]=='1'

    def set_remember_enabled(self, enabled):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES ('remember_corrections',?)", ('1' if enabled else '0',))

    def remembered_terms(self):
        with self.lock:
            rows=[dict(r) for r in self.db.execute('''SELECT source,target,COUNT(*) AS examples,
                MAX(updated_at) AS updated_at FROM correction_terms GROUP BY source,target
                ORDER BY updated_at DESC''')]
            disabled={r[0] for r in self.db.execute('SELECT source FROM disabled_correction_terms')}
            manual=dict(self.db.execute('SELECT source,target FROM glossary'))
        targets={}
        for row in rows:
            targets.setdefault(row['source'],set()).add(row['target'])
        pairs={(r['source'],r['target']) for r in rows}
        for row in rows:
            row['conflict']=len(targets[row['source']])>1 or (row['target'],row['source']) in pairs
            row['enabled']=row['source'] not in disabled
            row['manual_override']=row['source'] in manual
            row['active']=row['enabled'] and not row['conflict'] and not row['manual_override']
        return rows[:500]

    def set_remembered_term(self, source, enabled):
        with self.lock, self.db:
            if not self.db.execute('SELECT 1 FROM correction_terms WHERE source=?',(source,)).fetchone():
                raise KeyError(source)
            if enabled:
                self.db.execute('DELETE FROM disabled_correction_terms WHERE source=?',(source,))
            else:
                self.db.execute('INSERT OR IGNORE INTO disabled_correction_terms VALUES (?)',(source,))

    def correction_history(self, *, limit=100):
        with self.lock:
            return [dict(r) for r in self.db.execute(
                'SELECT * FROM correction_history ORDER BY updated_at DESC LIMIT ?', (limit,))]

    def correct(self, sid, segid, text, revision):
        with self.lock, self.db:
            row = self.get(sid, segid)
            if row is None:
                raise KeyError(segid)
            if row["status"] == "provisional":
                raise ValueError("暫定字幕尚未確認，請等候辨識完成。")
            if row["revision"] != revision:
                raise ValueError("這段文字已在其他畫面修改，請重新載入後再儲存。")
            previous=self.db.execute('SELECT original_text FROM correction_history WHERE segment_id=?',(segid,)).fetchone()
            baseline=self.db.execute('SELECT text FROM asr_baselines WHERE segment_id=?',(segid,)).fetchone()
            original=previous[0] if previous else baseline[0] if baseline else row['text']
            if text != row['text']:
                # A human undoing an automatic replacement disables that rule.
                for term in self.remembered_terms():
                    if term['active'] and term['source'] in original and term['source'] in text and term['target'] in row['text'] and term['target'] not in text:
                        self.db.execute('INSERT OR IGNORE INTO disabled_correction_terms VALUES (?)',(term['source'],))
                self.db.execute('''INSERT INTO correction_history VALUES (?,?,?,?,?)
                    ON CONFLICT(segment_id) DO UPDATE SET corrected_text=excluded.corrected_text,updated_at=excluded.updated_at''',
                    (segid,sid,original,text,now()))
                # Recompute from the ASR baseline, not the previous auto-save.
                # Superseded partial edits therefore stop affecting later ASR.
                self.db.execute('DELETE FROM correction_terms WHERE segment_id=?',(segid,))
                if self.remember_enabled():
                    self.db.executemany('INSERT INTO correction_terms VALUES (?,?,?,?)',
                        [(segid,p['source'],p['target'],now()) for p in term_changes(original,text)])
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


def export_transcript(session, segments, fmt, recordings=None):
    if fmt == "json":
        result = {"schema_version": 1, "session": session, "segments": segments}
        if recordings is not None:
            result['recordings'] = recordings
        return json.dumps(result, ensure_ascii=False, indent=2)
    if fmt == "srt":
        return "\n\n".join(f"{i}\n{timestamp(r['start'], True)} --> {timestamp(r['end'], True)}\n{r['text']}"
                           for i, r in enumerate((r for r in segments if r["status"] != "provisional" and r["text"]), 1)) + "\n"
    labels = {"provisional": "暫定／未確認", "committed": "AI 確認", "human_corrected": "人工校正／已鎖定"}
    lines = [session["title"], f"建立時間：{session['created_at']}", ""]
    lines += [f"[{timestamp(r['start'])} → {timestamp(r['end'])}] [{labels[r['status']]}]\n{r['text']}\n" for r in segments]
    return "\n".join(lines)
