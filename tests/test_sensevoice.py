from types import SimpleNamespace
import numpy as np
from fastapi.testclient import TestClient
from caption.sensevoice_engine import SenseVoiceEngine
from caption.server import create_app
from test_stream import VOICE
from test_api import receive_until


class Converter:
    def convert(self, text): return text


class Model:
    def __init__(self): self.inputs=[]
    def create_stream(self):
        model=self
        class Stream:
            def accept_waveform(self,rate,audio):
                assert rate==16000
                model.inputs.append(audio.copy())
            result=SimpleNamespace(text='語用，交談。')
        return Stream()
    def decode_stream(self,stream): pass


def test_whole_context_preview_punctuation_and_separate_streams():
    model=Model();engine=SenseVoiceEngine(model,Converter());session=engine.new_session()
    first=np.zeros(38400,np.float32);second=np.ones(64000,np.float32)
    assert session.recognize('a',first,False)=='語用，交談'
    assert session.recognize('a',second,True)=='語用，交談。'
    np.testing.assert_array_equal(model.inputs[1],second)


def test_sensevoice_capture_still_preserves_human_lock(tmp_path):
    engine=SenseVoiceEngine(Model(),Converter())
    with TestClient(create_app(tmp_path/'sensevoice.db',engine)) as client:
        assert client.get('/api/health').json()['backend']=='sensevoice'
        sid=client.post('/api/sessions',json={}).json()['id']
        with client.websocket_connect(f'/api/sessions/{sid}/audio') as ws:
            ws.receive_json();ws.receive_json()
            for _ in range(24):ws.send_bytes(VOICE)
            assert receive_until(ws,'segment','provisional',text=True)['segment']['text']=='語用，交談'
            ws.send_json({'type':'stop'})
            final=receive_until(ws,'segment','committed')['segment']
            receive_until(ws,'stopped')
        saved=client.patch(f'/api/sessions/{sid}/segments/{final["id"]}',json={'text':'人工正確文字','revision':final['revision']}).json()
        assert saved['locked'] and saved['status']=='human_corrected'
        late=client.app.state.store.apply_asr(sid,final['id'],'晚到的辨識',5,True)
        assert late['text']=='人工正確文字'
