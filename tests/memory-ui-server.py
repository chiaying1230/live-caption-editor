import sys
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from caption.server import create_app

class Engine:
    name='Memory UI fixture'
    model=True
    device='cpu'
    def load(self):pass
    def transcribe(self,audio):return '今天討論神性障礙者與小額麻痺。'

app=create_app(f'work/memory-ui-{uuid.uuid4().hex}/captions.sqlite3',Engine())
store=app.state.store
if not store.sessions():
    sid=store.create_session('自動修正詞彙 UI 測試')['id']
    for start in [0,8]:
        seg=store.begin(sid,start,start+8)
        store.apply_asr(sid,seg,'今天討論神性障礙者與小額麻痺。',start+8,True)
uvicorn.run(app,host='127.0.0.1',port=8012)
