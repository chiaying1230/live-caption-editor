from fastapi.testclient import TestClient
from caption.server import create_app
from test_api import FakeEngine


def test_glossary_persistence_literal_longest_match_and_human_protection(tmp_path):
    db = tmp_path/'terms.db'
    with TestClient(create_app(db,FakeEngine())) as client:
        sid=client.post('/api/sessions',json={}).json()['id']
        store=client.app.state.store
        before=store.begin(sid,0,1)
        store.apply_asr(sid,before,'甲乙',1,True)
        entries=[{'source':'甲','target':'乙'},{'source':'甲乙','target':'詞組'},
                 {'source':'乙','target':'丙'},{'source':'a.b','target':'正詞'}]
        assert client.put('/api/glossary',json={'entries':entries}).status_code==200
        assert store.get(sid,before)['text']=='甲乙'  # No retroactive transcript edits.
        seg=store.begin(sid,1,2)
        preview=store.apply_asr(sid,seg,'甲乙、甲、a.b、axb',2)
        assert preview['text']=='詞組、乙、正詞、axb'
        final=store.apply_asr(sid,seg,'甲乙',2,True)
        saved=client.patch(f'/api/sessions/{sid}/segments/{seg}',json={'text':'甲乙，人手保留','revision':final['revision']}).json()
        assert saved['text']=='甲乙，人手保留' and saved['locked']
        assert store.apply_asr(sid,seg,'甲乙',3,True)['text']==saved['text']
    with TestClient(create_app(db,FakeEngine())) as client:
        assert len(client.get('/api/glossary').json()['entries'])==4


def test_glossary_rejects_invalid_or_duplicate_terms_atomically(tmp_path):
    with TestClient(create_app(tmp_path/'terms.db',FakeEngine())) as client:
        valid={'source':'錯詞','target':'正詞'}
        assert client.put('/api/glossary',json={'entries':[valid]}).status_code==200
        for entries in ([valid,valid],[{'source':'','target':'正'}],
                        [{'source':'甲','target':'甲'}],[{'source':'甲\n乙','target':'丙'}],
                        [{'source':' 甲','target':'乙'}]):
            assert client.put('/api/glossary',json={'entries':entries}).status_code==422
            assert client.get('/api/glossary').json()['entries']==[valid]
        assert client.put('/api/glossary',json={'entries':[valid]},headers={'Origin':'https://example.com'}).status_code==403
