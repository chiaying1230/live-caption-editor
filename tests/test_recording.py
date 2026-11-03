import io
import sqlite3
import time
import wave

from fastapi.testclient import TestClient

from caption.recording import AudioArchive, RecordingError, WavRecording
from caption.server import create_app
from caption.store import Store
from test_api import FakeEngine, receive_until
from test_stream import VOICE, SILENCE


def capture(client, sid, frames):
    with client.websocket_connect(f'/api/sessions/{sid}/audio') as ws:
        ws.receive_json()
        ready=ws.receive_json()
        for frame in frames:
            ws.send_bytes(frame)
        ws.send_json({'type':'stop'})
        receive_until(ws,'stopped')
    return ready


def rows(client, sid):
    return client.get(f'/api/sessions/{sid}/recordings').json()['recordings']


def wav_data(client, sid, rid):
    response=client.get(f'/api/sessions/{sid}/recordings/{rid}/audio?download=true')
    assert response.status_code==200
    assert 'attachment' in response.headers['content-disposition']
    with wave.open(io.BytesIO(response.content),'rb') as audio:
        assert (audio.getnchannels(),audio.getsampwidth(),audio.getframerate())==(1,2,16000)
        return audio.readframes(audio.getnframes())


def test_complete_audio_includes_silence_and_download_is_session_scoped(tmp_path):
    with TestClient(create_app(tmp_path/'db.sqlite3',FakeEngine())) as client:
        sid=client.post('/api/sessions',json={}).json()['id']
        other=client.post('/api/sessions',json={}).json()['id']
        frames=[SILENCE]*10+[VOICE]*12+[SILENCE]*10
        capture(client,sid,frames)
        row=rows(client,sid)[0]
        assert row['status']=='complete' and row['duration']==3.2
        assert wav_data(client,sid,row['id'])==b''.join(frames)
        assert client.get(f'/api/sessions/{other}/recordings/{row["id"]}/audio').status_code==404
        assert client.get(f'/api/sessions/{sid}/recordings/no-such-file/audio').status_code==404
        assert client.get(f'/api/sessions/{sid}/export/json').json()['recordings'][0]['id']==row['id']
        # Browser audio controls can use HTTP ranges and inline disposition.
        response=client.get(f'/api/sessions/{sid}/recordings/{row["id"]}/audio',headers={'Range':'bytes=0-43'})
        assert response.status_code==206 and response.content[:4]==b'RIFF'
        assert 'inline' in response.headers['content-disposition']


def test_resume_after_silence_uses_audio_time_and_never_overwrites(tmp_path):
    with TestClient(create_app(tmp_path/'db.sqlite3',FakeEngine())) as client:
        sid=client.post('/api/sessions',json={}).json()['id']
        assert capture(client,sid,[SILENCE]*10)['offset']==0
        assert capture(client,sid,[VOICE]*4)['offset']==1
        recordings=rows(client,sid)
        assert len(recordings)==2 and recordings[0]['id']!=recordings[1]['id']
        assert recordings[1]['start']==1 and recordings[1]['end']==1.4
        assert wav_data(client,sid,recordings[0]['id'])==SILENCE*10
        assert wav_data(client,sid,recordings[1]['id'])==VOICE*4
        segments=client.get(f'/api/sessions/{sid}').json()['segments']
        assert segments[0]['start']==1 and segments[0]['end']==1.4


def test_recording_download_blocked_until_stop_and_bad_frames_not_saved(tmp_path):
    with TestClient(create_app(tmp_path/'db.sqlite3',FakeEngine())) as client:
        sid=client.post('/api/sessions',json={}).json()['id']
        with client.websocket_connect(f'/api/sessions/{sid}/audio') as ws:
            ws.receive_json();ws.receive_json()
            rid=rows(client,sid)[0]['id']
            assert client.get(f'/api/sessions/{sid}/recordings/{rid}/audio').status_code==409
            ws.send_bytes(b'bad')
            assert ws.receive_json()['type']=='error'
            receive_until(ws,'stopped')
        assert rows(client,sid)==[]
        assert not list((tmp_path/'recordings').glob('*.wav'))


def test_disconnect_retains_audio_as_interrupted(tmp_path):
    with TestClient(create_app(tmp_path/'db.sqlite3',FakeEngine())) as client:
        sid=client.post('/api/sessions',json={}).json()['id']
        with client.websocket_connect(f'/api/sessions/{sid}/audio') as ws:
            ws.receive_json();ws.receive_json()
            for _ in range(10): ws.send_bytes(SILENCE)
            receive_until(ws,'audio')
        for _ in range(100):
            if not client.get('/api/health').json()['busy']: break
            time.sleep(.01)
        row=rows(client,sid)[0]
        assert row['status']=='interrupted'
        assert wav_data(client,sid,row['id'])==SILENCE*10


def test_restart_recovers_wav_duration_before_next_capture(tmp_path):
    path=tmp_path/'db.sqlite3'
    store=Store(path)
    sid=store.create_session('錄音復原')['id']
    archive=AudioArchive(store,tmp_path/'recordings')
    recording=archive.start(sid,0)
    for _ in range(4): recording.write(VOICE)
    # Simulate a process disappearing before final metadata was committed.
    recording.audio.close();recording.file.close();store.close()
    with TestClient(create_app(path,FakeEngine())) as client:
        row=rows(client,sid)[0]
        assert row['status']=='interrupted' and row['duration']==.4
        assert wav_data(client,sid,row['id'])==VOICE*4
        assert capture(client,sid,[SILENCE])['offset']==.4


def test_disk_error_stops_capture_and_preserves_previous_audio(tmp_path,monkeypatch):
    original=WavRecording.write
    def disk_full(self,pcm):
        if self.samples>=16000: raise RecordingError('simulated disk full')
        original(self,pcm)
    monkeypatch.setattr(WavRecording,'write',disk_full)
    with TestClient(create_app(tmp_path/'db.sqlite3',FakeEngine())) as client:
        sid=client.post('/api/sessions',json={}).json()['id']
        with client.websocket_connect(f'/api/sessions/{sid}/audio') as ws:
            ws.receive_json();ws.receive_json()
            for _ in range(11):ws.send_bytes(SILENCE)
            assert '錄音' in receive_until(ws,'error')['message']
            receive_until(ws,'stopped')
        row=rows(client,sid)[0]
        assert row['status']=='interrupted'
        assert wav_data(client,sid,row['id'])==SILENCE*10
        assert client.get('/api/health').json()['busy'] is False


def test_metadata_failure_also_releases_capture_and_can_recover(tmp_path,monkeypatch):
    path=tmp_path/'db.sqlite3'
    with TestClient(create_app(path,FakeEngine())) as client:
        sid=client.post('/api/sessions',json={}).json()['id']
        def full_database(*args,**kwargs):
            raise sqlite3.OperationalError('simulated database disk full')
        monkeypatch.setattr(client.app.state.store,'update_recording',full_database)
        with client.websocket_connect(f'/api/sessions/{sid}/audio') as ws:
            ws.receive_json();ws.receive_json()
            for _ in range(10):ws.send_bytes(SILENCE)
            receive_until(ws,'error');receive_until(ws,'stopped')
        assert client.get('/api/health').json()['busy'] is False
    with TestClient(create_app(path,FakeEngine())) as client:
        row=rows(client,sid)[0]
        assert row['status']=='interrupted'
        assert wav_data(client,sid,row['id'])==SILENCE*10
