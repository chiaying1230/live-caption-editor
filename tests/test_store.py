import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from caption.store import Store, export_transcript


@pytest.fixture
def db(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    yield store
    store.close()


def test_late_asr_never_overwrites_committed_or_human_text(db):
    sid = db.create_session("課堂")["id"]
    segid = db.begin(sid, 0, 1)
    db.apply_asr(sid, segid, "暫時", 1)
    committed = db.apply_asr(sid, segid, "確認", 2, True)
    assert db.apply_asr(sid, segid, "晚到的暫定", 1)["text"] == "確認"
    corrected = db.correct(sid, segid, "聽打員校正", committed["revision"])
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: db.apply_asr(sid, segid, "錯誤覆寫", 99, True), range(20)))
    assert all(row == corrected for row in results)
    assert corrected["locked"] and corrected["status"] == "human_corrected"
    assert corrected["start"] == 0 and corrected["end"] == 2


def test_revision_conflict_and_provisional_edit_rejected(db):
    sid = db.create_session("課堂")["id"]
    segid = db.begin(sid, 1, 2)
    with pytest.raises(ValueError):
        db.correct(sid, segid, "尚未確認", 0)
    row = db.apply_asr(sid, segid, "辨識", 3, True)
    db.correct(sid, segid, "", row["revision"])
    with pytest.raises(ValueError):
        db.correct(sid, segid, "舊版本", row["revision"])
    assert db.get(sid, segid)["text"] == ""  # Deleting a hallucination is a valid correction.


def test_persistence_and_exports(db):
    session = db.create_session("繁體中文聽打")
    sid = session["id"]
    segid = db.begin(sid, 1.123, 2.456)
    row = db.apply_asr(sid, segid, "學習語音辨識。", 2.456, True)
    db.correct(sid, segid, "學習即時聽打。", row["revision"])
    pending = db.begin(sid, 3, 4)
    db.apply_asr(sid, pending, "未確認", 4)
    other = Store(db.db.execute("PRAGMA database_list").fetchone()[2])
    rows = other.segments(sid)
    other.close()
    parsed = json.loads(export_transcript(session, rows, "json"))
    assert parsed["segments"][0]["locked"] is True
    txt = export_transcript(session, rows, "txt")
    assert "人工校正／已鎖定" in txt and "暫定／未確認" in txt
    srt = export_transcript(session, rows, "srt")
    assert "00:00:01,123 --> 00:00:02,456" in srt
    assert "學習即時聽打。" in srt and "未確認" not in srt
