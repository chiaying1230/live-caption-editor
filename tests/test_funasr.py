import numpy as np
import pytest
from fastapi.testclient import TestClient

from caption.funasr_engine import FunASREngine, result_text
from caption.server import create_app
from test_api import receive_until
from test_stream import VOICE, SILENCE


class Converter:
    def convert(self, text):
        return text


class Online:
    def __init__(self):
        self.calls = []

    def generate(self, *, input, cache, **kwargs):
        self.calls.append(input.copy())
        cache["n"] = cache.get("n", 0) + 1
        return [{"text":str(cache["n"])}]


class Offline:
    def __init__(self):
        self.calls = []

    def generate(self, *, input, **kwargs):
        self.calls.append(input.copy())
        return [{"text":"完整校正"}]


def test_coalesced_snapshots_feed_each_sample_once_and_finalize_full_audio():
    online, offline = Online(), Offline()
    session = FunASREngine(online, offline, Converter(), chunk_ms=600).new_session()
    audio = np.arange(28800, dtype=np.float32)
    assert session.recognize("a", audio[:9600], False) == "1"
    assert session.recognize("a", audio[:9600], False) == "1"
    assert session.recognize("a", audio, False) == "123"
    np.testing.assert_array_equal(np.concatenate(online.calls), audio)
    assert session.recognize("a", audio, True) == "完整校正"
    np.testing.assert_array_equal(offline.calls[0], audio)
    assert session.consumed == 0 and session.cache == {}
    assert session.recognize("b", audio[:9600], False) == "1"


def test_capture_caches_are_independent_and_final_can_skip_previews():
    online, offline = Online(), Offline()
    engine = FunASREngine(online, offline, Converter(), chunk_ms=600)
    first, second = engine.new_session(), engine.new_session()
    audio = np.zeros(9600, np.float32)
    assert first.recognize("a", audio, False) == "1"
    assert second.recognize("b", audio, False) == "1"
    assert first.recognize("a", np.zeros(19200, np.float32), False) == "12"
    assert second.recognize("c", audio[:1600], True) == "完整校正"
    assert len(offline.calls) == 1


@pytest.mark.parametrize("invalid", [None, {}, [{"text":3}], ["text"]])
def test_invalid_model_result_is_not_committed_as_text(invalid):
    with pytest.raises(RuntimeError):
        result_text(invalid)


def test_funasr_endpoint_uses_streaming_then_offline_with_human_lock(tmp_path):
    engine = FunASREngine(Online(), Offline(), Converter(), chunk_ms=600)
    with TestClient(create_app(tmp_path / "funasr.db", engine)) as client:
        assert client.get('/api/health').json()['backend'] == 'funasr'
        sid = client.post('/api/sessions', json={}).json()['id']
        with client.websocket_connect(f'/api/sessions/{sid}/audio') as ws:
            ws.receive_json(); ws.receive_json()
            for _ in range(6):
                ws.send_bytes(VOICE)
            assert receive_until(ws, 'segment', 'provisional', text=True)['segment']['text'] == '1'
            for _ in range(8):
                ws.send_bytes(SILENCE)
            row = receive_until(ws, 'segment', 'committed')['segment']
            assert row['text'] == '完整校正'
            saved = client.patch(f'/api/sessions/{sid}/segments/{row["id"]}', json={
                'text':'人工校正內容','revision':row['revision']}).json()
            assert saved['locked'] is True
            ws.send_json({'type':'stop'})
            receive_until(ws, 'stopped')
        assert client.get(f'/api/sessions/{sid}').json()['segments'][0]['text'] == '人工校正內容'


def test_final_punctuation_is_applied_before_conversion():
    class Punctuation:
        def generate(self, *, input, **kwargs):
            return [{'text':input + '。'}]
    engine = FunASREngine(Online(), Offline(), Converter(), chunk_ms=600)
    engine.punctuation = Punctuation()
    assert engine.new_session().recognize('a', np.zeros(1600,np.float32), True) == '完整校正。'


def test_coalesced_previews_publish_each_chunk_with_punctuation():
    class Punctuation:
        def __init__(self):
            self.inputs = []
        def generate(self, *, input, **kwargs):
            self.inputs.append(input)
            return [{'text':input[:1] + '，' + input[1:] + '。'}]
    engine = FunASREngine(Online(), Offline(), Converter(), chunk_ms=1200)
    engine.punctuation = Punctuation()
    recognizer = engine.new_session()
    events = []
    text = recognizer.recognize('a', np.zeros(57600,np.float32), False,
                                lambda text, consumed: events.append((text,consumed)))
    assert events == [('1',19200),('1，2',38400),('1，23',57600)]
    assert text == '1，23'
    assert engine.punctuation.inputs == ['1','12','123']  # No duplicate final call.


def test_pending_preview_is_delivered_before_slower_final(tmp_path):
    import asyncio
    from caption.store import Store
    from caption.stream import AudioStream
    async def scenario():
        store = Store(tmp_path/'pending.db')
        sid = store.create_session('待處理預覽')['id']
        engine = FunASREngine(Online(), Offline(), Converter(), chunk_ms=600)
        events = []
        async def send(event):
            events.append(event)
        stream = AudioStream(store,sid,engine,send)
        # Simulate the worker being busy until after a pause has queued a final.
        for _ in range(18):
            await stream.feed(VOICE)
        for _ in range(8):
            await stream.feed(SILENCE)
        await stream.finish()
        await stream.run()
        rows=[e['segment'] for e in events if e['type']=='segment' and e['segment']['text']]
        assert rows[0]['status']=='provisional'
        assert rows[0]['text']=='1'
        assert any(r['text']=='12' for r in rows[:-1])
        assert rows[-1]['status']=='committed' and rows[-1]['text']=='完整校正'
        assert all(a['end']<=b['end'] for a,b in zip(rows,rows[1:]))
        store.close()
    asyncio.run(scenario())
