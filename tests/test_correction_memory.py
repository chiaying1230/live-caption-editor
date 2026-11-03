from fastapi.testclient import TestClient
from caption.server import create_app
from test_api import FakeEngine
from caption.corrections import term_changes


def segment(client, text):
    store=client.app.state.store
    sid=client.post('/api/sessions',json={}).json()['id']
    segid=store.begin(sid,0,2)
    return sid,store.apply_asr(sid,segid,text,2,True)


def save(client,sid,row,text):
    result=client.patch(f'/api/sessions/{sid}/segments/{row["id"]}',json={'text':text,'revision':row['revision']})
    assert result.status_code==200
    return result.json()


def memory(client):
    return client.get('/api/correction-memory').json()


def test_small_edits_remember_contextual_words_apply_future_asr_and_persist(tmp_path):
    path=tmp_path/'memory.db'
    with TestClient(create_app(path,FakeEngine())) as client:
        sid,row=segment(client,'這位神性障礙者提到小額麻痺的經驗。')
        saved=save(client,sid,row,'這位身心障礙者提到小兒麻痺的經驗。')
        assert saved['locked']
        terms=memory(client)['terms']
        assert {(r['source'],r['target']) for r in terms}=={('神性障礙者','身心障礙者'),('小額麻痺','小兒麻痺')}
        assert all(r['active'] for r in terms)
        store=client.app.state.store
        new=store.begin(sid,2,4)
        assert store.apply_asr(sid,new,'神性障礙者與小額麻痺。',4,True)['text']=='身心障礙者與小兒麻痺。'
        assert store.apply_asr(sid,row['id'],'過期辨識',9,True)['text']==saved['text']
    with TestClient(create_app(path,FakeEngine())) as client:
        assert len(memory(client)['terms'])==2
        assert len(memory(client)['history'])==1
        exported=client.get('/api/correction-memory/export')
        assert exported.status_code==200 and not exported.json()['whole_segments_human_verified']


def test_autosave_updates_evidence_from_original_and_undo_removes_rule(tmp_path):
    with TestClient(create_app(tmp_path/'memory.db',FakeEngine())) as client:
        sid,row=segment(client,'神性障礙者')
        row=save(client,sid,row,'身性障礙者')
        row=save(client,sid,row,'身心障礙者')
        data=memory(client)
        assert [(r['source'],r['target']) for r in data['terms']]==[('神性障礙者','身心障礙者')]
        assert data['history'][0]['original_text']=='神性障礙者'
        assert data['history'][0]['corrected_text']=='身心障礙者'
        save(client,sid,row,'神性障礙者')
        assert memory(client)['terms']==[]


def test_rewrite_punctuation_numbers_pronouns_and_insertions_only_leave_history(tmp_path):
    cases=[('神性障礙者。','神性障礙者！'),('他是一位老師。','她是一位老師。'),
           ('日期是二零二五年。','日期是二零二六年。'),
           ('今天這堂課要討論很多種不同的事情。','講者重新整理整個段落並改用全新的表達方式。'),
           ('他是一位。','他是一位女性。')]
    with TestClient(create_app(tmp_path/'memory.db',FakeEngine())) as client:
        for before,after in cases:
            sid,row=segment(client,before);save(client,sid,row,after)
        # Chinese numeral edits are also context-dependent, not reusable terms.
        assert memory(client)['terms']==[]
        assert len(memory(client)['history'])==len(cases)


def test_disable_manual_override_and_conflicting_targets(tmp_path):
    with TestClient(create_app(tmp_path/'memory.db',FakeEngine())) as client:
        sid,row=segment(client,'神性障礙者');save(client,sid,row,'身心障礙者')
        assert client.patch('/api/correction-memory/terms',json={'source':'神性障礙者','enabled':False}).status_code==200
        assert not memory(client)['terms'][0]['active']
        client.patch('/api/correction-memory/terms',json={'source':'神性障礙者','enabled':True})
        assert memory(client)['terms'][0]['active']
        client.put('/api/glossary',json={'entries':[{'source':'神性障礙者','target':'手動指定'}]})
        assert not memory(client)['terms'][0]['active']
        store=client.app.state.store;new=store.begin(sid,2,3)
        assert store.apply_asr(sid,new,'神性障礙者',3,True)['text']=='手動指定'
        client.put('/api/glossary',json={'entries':[]})
        sid2,row2=segment(client,'神性障礙者');save(client,sid2,row2,'神經障礙者')
        assert all(r['conflict'] and not r['active'] for r in memory(client)['terms'])
        new=store.begin(sid,3,4)
        assert store.apply_asr(sid,new,'神性障礙者',4,True)['text']=='神性障礙者'


def test_turn_off_learning_and_failed_revision_have_no_terms(tmp_path):
    with TestClient(create_app(tmp_path/'memory.db',FakeEngine())) as client:
        client.put('/api/correction-memory',json={'enabled':False})
        sid,row=segment(client,'神性障礙者');saved=save(client,sid,row,'身心障礙者')
        assert memory(client)['terms']==[] and memory(client)['history']
        response=client.patch(f'/api/sessions/{sid}/segments/{row["id"]}',json={'text':'神經障礙者','revision':row['revision']})
        assert response.status_code==409
        assert memory(client)['history'][0]['corrected_text']==saved['text']
        assert client.put('/api/correction-memory',json={'enabled':True},headers={'Origin':'https://example.com'}).status_code==403


def test_human_undo_of_an_automatic_replacement_disables_it(tmp_path):
    with TestClient(create_app(tmp_path/'memory.db',FakeEngine())) as client:
        sid,row=segment(client,'神性障礙者');save(client,sid,row,'身心障礙者')
        sid2,row2=segment(client,'神性障礙者')
        assert row2['text']=='身心障礙者'
        save(client,sid2,row2,'神性障礙者')
        term=memory(client)['terms'][0]
        assert not term['enabled'] and not term['active']
        sid3,row3=segment(client,'神性障礙者')
        assert row3['text']=='神性障礙者'


def test_word_boundaries_exclude_neighboring_garbage_and_grammatical_rewrites():
    assert term_changes('無障礙的色及胃咖啡色','無障礙的設計胃咖啡色')==[{'source':'色及','target':'設計'}]
    assert term_changes('學生髮展的能力','學生發展的能力')==[{'source':'髮展','target':'發展'}]
    assert term_changes('提供適當的知持','提供適當的支持')==[{'source':'知持','target':'支持'}]
    assert term_changes('不要不要嫌棄他們','不要不要先替他們')==[]
    assert term_changes('不管幹什麼樣的話','不管在什麼樣的環境')==[]
