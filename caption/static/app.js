const $ = (id) => document.getElementById(id);
const labels = {provisional: '暫定', committed: 'AI 確認', human_corrected: '人工校正 · 已鎖定'};
let session = null, segments = new Map(), cards = new Map(), drafts = new Set();
let state = 'idle', ws = null, context = null, media = null, source = null, processor = null, sink = null;
let flushResolve = null;
let polling = false;
let glossaryDirty = false;
let recordingSignature = '';
let navigating = false;
let inputFrames = 0, lastAudioAt = 0, recordingSince = 0, inputRms = 0, threshold = .003;
let receivedSeconds = 0, hasRecognizedText = false;
let following = true, scrollPending = false, scrollVersion = 0, currentEdit = null;
const inlineEdits = new Map();
const viewport = $('caption-viewport');
function savingEdits() { return [...inlineEdits.values()].some(edit => edit.saving); }

function followLatest() {
  if (!following || currentEdit) return;
  scrollPending = true;
  const version=++scrollVersion;
  requestAnimationFrame(() => {
    if(version!==scrollVersion) return;
    if(!following || currentEdit) { scrollPending=false; return; }
    viewport.scrollTop = viewport.scrollHeight;
    requestAnimationFrame(() => { if(version===scrollVersion) scrollPending = false; });
  });
}
function setFollowing(value) {
  if (value && currentEdit) return;
  following = value;
  $('follow-latest').hidden = value || !!currentEdit;
  if (value) followLatest();
}
viewport.addEventListener('wheel', event => { if (event.deltaY < 0) setFollowing(false); }, {passive:true});
viewport.addEventListener('touchstart', () => setFollowing(false), {passive:true});
viewport.addEventListener('keydown', event => {
  if (['ArrowUp','PageUp','Home'].includes(event.key)) setFollowing(false);
  if (event.key === 'End') setFollowing(true);
});
viewport.addEventListener('scroll', () => {
  if (scrollPending) return;
  setFollowing(viewport.scrollHeight - viewport.clientHeight - viewport.scrollTop < 24);
}, {passive:true});
$('follow-latest').onclick = () => { currentEdit?.element.blur(); setFollowing(true); };
function layoutCaptionSpace() {
  const dock = document.querySelector('.control-dock').getBoundingClientRect().height;
  document.documentElement.style.setProperty('--dock-space', `${dock}px`);
  followLatest();
}
new ResizeObserver(layoutCaptionSpace).observe(document.querySelector('.control-dock'));
window.addEventListener('resize', layoutCaptionSpace);
function setFontSize(value) {
  const size = Math.min(112, Math.max(36, Number(value) || 64));
  $('caption-size').value = size; $('font-size-value').textContent = size;
  document.documentElement.style.setProperty('--caption-size', `${size}px`);
  localStorage.setItem('caption-font-size', size); followLatest();
}
setFontSize(localStorage.getItem('caption-font-size'));
$('caption-size').oninput = event => setFontSize(event.target.value);
$('fullscreen').onclick = async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch { notice('無法切換全螢幕，可按 F11 放大瀏覽器。'); }
};
document.addEventListener('fullscreenchange', () => {
  $('fullscreen').textContent = document.fullscreenElement ? '⛶ 離開全螢幕' : '⛶ 全螢幕'; layoutCaptionSpace();
});
function showSettings(show) {
  $('settings').hidden = !show; $('settings-toggle').setAttribute('aria-expanded', String(show));
  if (show) $('settings-close').focus();
}
$('settings-toggle').onclick = () => showSettings($('settings').hidden);
$('settings-close').onclick = () => { showSettings(false); $('settings-toggle').focus(); };
$('settings').addEventListener('keydown', event => { if (event.key === 'Escape') showSettings(false); });

async function loadGlossary() {
  const data=await api('/api/glossary');
  $('glossary-text').value=data.entries.map(entry=>`${entry.source} → ${entry.target}`).join('\n');
  $('glossary-status').textContent=`已儲存 ${data.entries.length} 組 · 只替換明確指定的錯詞`;
}
$('glossary-save').onclick=async()=>{
  const button=$('glossary-save'); button.disabled=true;
  try {
    const entries=$('glossary-text').value.split(/\r?\n/).filter(line=>line.trim()).map((line,index)=>{
      const parts=line.split(/\t+|\s*→\s*|\s*=>\s*/).map(part=>part.trim());
      if(parts.length!==2 || !parts[0] || !parts[1]) throw new Error(`第 ${index+1} 行請使用「錯詞 → 正確詞」或兩欄 Tab 格式。`);
      if(parts.some(part=>part.length>100)) throw new Error(`第 ${index+1} 行的詞彙超過 100 字，請縮短。`);
      return {source:parts[0],target:parts[1]};
    });
    if(entries.length>500) throw new Error('最多可儲存 500 組，請先挑選常用的錯詞。');
    const data=await api('/api/glossary',{method:'PUT',body:JSON.stringify({entries})}); glossaryDirty=false;
    $('glossary-status').textContent=`已儲存 ${data.entries.length} 組，下次 AI 更新起生效。`; notice();
  } catch(error) { $('glossary-status').textContent=error.message; }
  finally { button.disabled=false; }
};
$('glossary-text').oninput=()=>{glossaryDirty=true; $('glossary-status').textContent='字彙表尚未儲存';};
function notice(message = '') { $('notice').textContent = message; $('notice').hidden = !message; }
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {'Content-Type': 'application/json', ...options.headers}});
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : '操作失敗，請檢查本機服務。');
  }
  return response.json();
}
function updateControls() {
  $('start').disabled = state !== 'idle' || !session || navigating;
  $('stop').disabled = !['preparing', 'recording'].includes(state);
  $('new-session').disabled = state !== 'idle' || navigating || savingEdits();
  $('export').disabled = !session || !segments.size || drafts.size > 0 || navigating || savingEdits();
  $('export').title = drafts.size ? '請先儲存或取消編輯，再匯出' : '';
  $('signal').classList.toggle('live', state === 'recording');
  $('audio-saving').hidden = !['recording','stopping'].includes(state);
  $('microphone').disabled = state !== 'idle';
  for (const button of $('sessions').children) button.disabled = state !== 'idle' || navigating || savingEdits();
  $('count').textContent = `${segments.size} 段`;
  $('empty').hidden = [...segments.values()].some(row => /[\p{L}\p{N}]/u.test(row.text));
  $('edit-latest').disabled = ![...segments.values()].some(row => row.status !== 'provisional') || navigating;
}
function setState(next, detail) {
  state = next;
  $('recording-status').textContent = {idle:'準備就緒',preparing:'準備模型與麥克風',recording:'正在收音',stopping:'收音已停止，正在完成辨識'}[next];
  $('recording-detail').textContent = detail || {idle:'按下開始收音，允許使用麥克風。',preparing:'首次使用需要下載模型，請保持連線。',recording:'暫定字幕會持續更新；稍作停頓後即可編輯。',stopping:'最後一段音訊處理完成後，會保留在逐字稿。'}[next];
  updateControls();
  if (['recording','stopping'].includes(state)) $('audio-recording-status').textContent = state==='recording' ? '同步錄音中，包含停頓與尚未辨識出文字的聲音。' : '正在保存錄音並完成字幕，請稍候。';
}

function renderRecordings(rows=[]) {
  const signature=JSON.stringify([session?.id,rows]);
  if (signature!==recordingSignature) {
    recordingSignature=signature;
    $('recordings').replaceChildren();
    for (const row of rows) {
      const item=node('div','recording-item');
      const duration=Math.round(row.duration);
      item.append(node('p','',`${new Date(row.created_at).toLocaleString('zh-TW')} · ${Math.floor(duration/60)} 分 ${duration%60} 秒 · 字幕 ${time(row.start)} 起`));
      if (row.status==='recording') item.append(node('small','','錄音中，停止後可回放與下載。'));
      else {
        if (row.status==='interrupted') item.append(node('small','','收音曾中斷，已保留收到的錄音。'));
        const url=`/api/sessions/${session.id}/recordings/${row.id}/audio`;
        const player=node('audio'); player.controls=true; player.preload='none'; player.src=url;
        const download=node('a','recording-download','↓ 下載 WAV 錄音');
        download.href=`${url}?download=true`; download.download='';
        item.append(player,download);
      }
      $('recordings').append(item);
    }
  }
  if (state==='idle') $('audio-recording-status').textContent=rows.length ? '錄音已保存在本機。可回放或下載；再次收音會另存一份。' : '開始收音時會同步保存錄音；舊字幕沒有錄音檔。只保存在這台電腦。';
}
async function refreshRecordings() {
  const sid=session?.id;
  if (!sid) return;
  const data=await api(`/api/sessions/${sid}`);
  if (session?.id===sid) renderRecordings(data.recordings);
}
async function refreshMicrophones() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  const selected = $('microphone').value;
  const devices = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'audioinput' && d.deviceId);
  $('microphone').replaceChildren(new Option('系統預設麥克風',''));
  devices.forEach((device, i) => $('microphone').add(new Option(device.label || `麥克風 ${i+1}`,device.deviceId)));
  if (devices.some(d => d.deviceId === selected)) $('microphone').value = selected;
}
function configureSensitivity() {
  if (ws?.readyState !== WebSocket.OPEN || !['preparing','recording'].includes(state)) return;
  threshold = Number($('sensitivity').value || threshold);
  ws.send(JSON.stringify({type:'configure',threshold}));
}
$('sensitivity').onchange = configureSensitivity;
navigator.mediaDevices?.addEventListener('devicechange', () => refreshMicrophones().catch(() => {}));
setInterval(() => {
  if (state !== 'recording') return;
  if (Date.now() - lastAudioAt > 3000 && Date.now() - recordingSince > 3000) {
    $('audio-status').textContent = '尚未收到麥克風音訊。請停止後改選麥克風；也請確認瀏覽器分頁沒有休眠。';
  } else if (inputFrames > 30 && inputRms < threshold) {
    $('audio-status').textContent = `已收到 ${receivedSeconds.toFixed(1)} 秒音訊，目前音量偏小。請對著麥克風說話；若仍無字幕，可把靈敏度改為「高」。`;
  }
}, 1000);
function time(value) {
  const secs = Math.floor(value), h = Math.floor(secs/3600), m = Math.floor(secs%3600/60), s = secs%60;
  return `${h ? String(h).padStart(2,'0') + ':' : ''}${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}
function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}
function upsert(row) {
  if (!session || row.session_id !== session.id) return;
  const previous = segments.get(row.id);
  if (previous && previous.revision > row.revision) return;
  if (previous && previous.revision === row.revision && previous.text === row.text && previous.status === row.status && previous.end === row.end) return;
  segments.set(row.id, row);
  let card = cards.get(row.id);
  if (!card) {
    card = node('article', 'segment'); card.dataset.id = row.id;
    const text = node('p', 'segment-text');
    const tools = node('div', 'inline-tools'); tools.hidden = true;
    const status = node('span', 'inline-status'), save = node('button', '', '儲存'), cancel = node('button', '', '取消');
    tools.append(status, save, cancel); card.append(text, tools);
    text.addEventListener('focus', () => beginInlineEdit(row.id));
    text.addEventListener('input', () => {
      const edit = inlineEdits.get(row.id); if (!edit) return;
      markDirty(edit); clearTimeout(edit.timer);
      if (!edit.conflict && !edit.composing) edit.timer = setTimeout(() => saveEdit(edit), 1200);
    });
    text.addEventListener('compositionstart', () => {
      const edit=inlineEdits.get(row.id); if (edit) { edit.composing=true; clearTimeout(edit.timer); }
    });
    text.addEventListener('compositionend', () => {
      const edit=inlineEdits.get(row.id); if (edit) { edit.composing=false; markDirty(edit); edit.timer=setTimeout(()=>saveEdit(edit),1200); }
    });
    text.addEventListener('blur', () => {
      const edit = inlineEdits.get(row.id); if (!edit) return;
      if (currentEdit === edit) { currentEdit = null; setFollowing(edit.wasFollowing); }
      saveEdit(edit);
    });
    text.addEventListener('keydown', event => {
      if (event.isComposing) return;
      const edit = inlineEdits.get(row.id); if (!edit) return;
      if (event.ctrlKey && event.key === 'Enter') { event.preventDefault(); saveEdit(edit); }
      if (event.key === 'Escape') { event.preventDefault(); cancelEdit(edit); }
    });
    // Clicking these controls should not blur the text and start another save.
    tools.addEventListener('pointerdown', event => event.preventDefault());
    save.onclick = () => saveEdit(inlineEdits.get(row.id));
    cancel.onclick = () => cancelEdit(inlineEdits.get(row.id));
    cards.set(row.id, card); $('segments').append(card);
  }
  const edit = inlineEdits.get(row.id), text = card.querySelector('.segment-text');
  card.className = `segment ${row.status}${edit ? ' editing' : ''}`;
  card.hidden = !edit && !/[\p{L}\p{N}]/u.test(row.text);
  card.title = `${labels[row.status]} · ${time(row.start)} — ${time(row.end)}`;
  text.contentEditable = row.status === 'provisional' ? 'false' : 'plaintext-only';
  if (row.status !== 'provisional') {
    text.setAttribute('role','textbox'); text.setAttribute('aria-multiline','true');
    text.setAttribute('aria-label',`編輯 ${time(row.start)} 字幕`);
  }
  if (!edit) text.textContent = row.text;
  updateControls(); followLatest();
}
function markDirty(edit) {
  const dirty = edit.element.innerText !== edit.original;
  if (dirty) drafts.add(edit.id); else drafts.delete(edit.id);
  const card = cards.get(edit.id);
  card.querySelector('.inline-status').textContent = edit.saving ? '儲存中…' : dirty ? '正在校正 · 停筆後自動儲存' : '點字即可修改 · 自動儲存';
  card.querySelectorAll('.inline-tools button').forEach(button => { button.disabled = edit.saving; });
  updateControls();
}
function beginInlineEdit(id) {
  const row = segments.get(id); if (!row || row.status === 'provisional') return;
  let edit = inlineEdits.get(id);
  if (!edit) {
    edit = {id, sid:session.id, element:cards.get(id).querySelector('.segment-text'), revision:row.revision, original:row.text, saving:false};
    inlineEdits.set(id,edit);
  }
  edit.wasFollowing = following; currentEdit = edit; setFollowing(false);
  cards.get(id).classList.add('editing'); cards.get(id).querySelector('.inline-tools').hidden = false;
  showSettings(false); markDirty(edit);
}
function releaseEdit(edit) {
  if (currentEdit === edit || drafts.has(edit.id) || edit.saving) return;
  inlineEdits.delete(edit.id);
  const card=cards.get(edit.id); if (!card) return;
  card.classList.remove('editing'); card.querySelector('.inline-tools').hidden = true;
  card.hidden = !/[\p{L}\p{N}]/u.test(segments.get(edit.id).text);
}
async function saveEdit(edit) {
  if (!edit || edit.saving || edit.composing) return;
  clearTimeout(edit.timer);
  const text=edit.element.innerText;
  if (text === edit.original) { drafts.delete(edit.id); releaseEdit(edit); updateControls(); return; }
  if (text.length > 20000) { notice('這句超過兩萬字，請縮短後再儲存；輸入仍保留。'); return; }
  edit.saving = true; markDirty(edit);
  try {
    const updated = await api(`/api/sessions/${edit.sid}/segments/${edit.id}`,{method:'PATCH',body:JSON.stringify({text,revision:edit.revision})});
    edit.revision=updated.revision; edit.original=updated.text; edit.conflict=false;
    upsert(updated); notice();
  } catch(error) {
    edit.conflict=true; notice(error.message + ' 你的修改仍在原句；請先複製文字再取消或重新載入。');
  } finally {
    edit.saving=false; markDirty(edit); releaseEdit(edit);
    if (drafts.has(edit.id) && !edit.conflict) edit.timer=setTimeout(()=>saveEdit(edit),1200);
  }
}
function cancelEdit(edit) {
  if (!edit || edit.saving) return;
  clearTimeout(edit.timer);
  const row=segments.get(edit.id); edit.element.textContent=row.text;
  edit.original=row.text; drafts.delete(edit.id); edit.element.blur();
  inlineEdits.delete(edit.id); cards.get(edit.id).classList.remove('editing');
  cards.get(edit.id).querySelector('.inline-tools').hidden=true;
  cards.get(edit.id).hidden=!/[\p{L}\p{N}]/u.test(row.text); notice(); updateControls();
}
$('edit-latest').onclick = () => {
  const row=[...segments.values()].filter(r=>r.status !== 'provisional' && /[\p{L}\p{N}]/u.test(r.text)).at(-1);
  if (row) cards.get(row.id).querySelector('.segment-text').focus();
};
async function loadSessions() {
  const rows = await api('/api/sessions');
  $('sessions').replaceChildren();
  for (const row of rows) {
    const button = node('button', row.id === session?.id ? 'selected' : '', row.title);
    button.append(node('small','',new Date(row.created_at).toLocaleString('zh-TW',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})));
    button.onclick = () => openSession(row.id).catch(error => notice(error.message));
    $('sessions').append(button);
  }
  updateControls();
  return rows;
}
async function openSession(id) {
  if (state !== 'idle' || navigating || savingEdits()) return;
  if (drafts.size) { notice('請先儲存或取消編輯，再切換聽打。'); return; }
  navigating = true; updateControls();
  try { await selectSession(id); }
  finally { navigating = false; updateControls(); }
}
async function selectSession(id) {
  const data = await api(`/api/sessions/${id}`);
  inlineEdits.clear(); currentEdit=null; setFollowing(true); showSettings(false);
  session = data.session;
  renderRecordings(data.recordings);
  localStorage.setItem('caption-session', session.id);
  $('title').textContent = session.title;
  segments.clear(); cards.clear(); $('segments').replaceChildren();
  for (const row of data.segments) upsert(row);
  await loadSessions(); updateControls();
  notice(data.recording ? '這場聽打仍在其他頁面收音或處理中；請先在原頁面停止。' : data.segments.some(r => r.status === 'provisional') ? '有上次中斷留下的暫定字幕，尚未經 AI 確認；TXT 與 JSON 匯出會保留並標示。' : '');
}
async function newSession() {
  if (state !== 'idle' || navigating || savingEdits()) return;
  if (drafts.size) { notice('請先儲存或取消編輯，再新增聽打。'); return; }
  navigating = true; updateControls();
  try {
    const title = `聽打 ${new Date().toLocaleString('zh-TW',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}`;
    const row = await api('/api/sessions',{method:'POST',body:JSON.stringify({title})});
    await selectSession(row.id);
  } finally { navigating = false; updateControls(); }
}
function releaseAudio() {
  media?.getTracks().forEach(track => track.stop()); media = null;
  source?.disconnect(); processor?.disconnect(); sink?.disconnect();
  source = processor = sink = null;
  if (context) { context.close().catch(() => {}); context = null; }
  $('input-level').value = 0;
}
async function stopCapture() {
  if (!['preparing','recording'].includes(state)) return;
  setState('stopping');
  if (processor) {
    // FIFO port messages ensure the padded final frame precedes the Stop command.
    await Promise.race([new Promise(resolve => { flushResolve = resolve; processor.port.postMessage('flush'); }),
      new Promise(resolve => setTimeout(() => { if (flushResolve) notice('音訊尾端送出逾時，最後不足 0.1 秒可能未保留。'); resolve(); }, 1500))]);
    flushResolve = null;
  }
  releaseAudio();
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({type:'stop'}));
  else { ws?.close(); setState('idle'); }
}
async function setupAudio(socket) {
  try {
    const chosen = $('microphone').value;
    const stream = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,
      noiseSuppression:false, ...(chosen ? {deviceId:{exact:chosen}} : {})},video:false});
    if (ws !== socket || state !== 'preparing' || socket.readyState !== WebSocket.OPEN) { stream.getTracks().forEach(t => t.stop()); return; }
    media = stream;
    await refreshMicrophones();
    context = new AudioContext();
    await context.audioWorklet.addModule('/static/pcm-worklet.js');
    if (state !== 'preparing' || socket !== ws) { releaseAudio(); return; }
    source = context.createMediaStreamSource(media);
    processor = new AudioWorkletNode(context,'pcm-capture',{numberOfInputs:1,numberOfOutputs:1,channelCount:1});
    sink = context.createGain(); sink.gain.value = 0;
    processor.port.onmessage = ({data}) => {
      if (data === 'flushed') { flushResolve?.(); return; }
      if (socket.readyState === WebSocket.OPEN && ['recording','stopping'].includes(state)) {
        const pcm = new Int16Array(data);
        inputRms = Math.sqrt(pcm.reduce((sum, value) => sum + (value/32768)**2, 0) / pcm.length);
        $('input-level').value = Math.max(0, Math.min(100, 100 + 30*Math.log10(Math.max(inputRms,1e-8))));
        inputFrames++; lastAudioAt = Date.now();
        if (socket.bufferedAmount > 16000 * 2 * 5) {
          notice('連線傳送速度不足，已停止收音。請檢查本機服務。');
          stopCapture(); return;
        }
        socket.send(data);
      }
    };
    source.connect(processor); processor.connect(sink); sink.connect(context.destination);
    await context.resume();
    if (state !== 'preparing') { releaseAudio(); return; }
    media.getTracks()[0].onended = () => { notice('麥克風已中斷，正在保留已收到的字幕。'); stopCapture(); };
    setState('recording');
    recordingSince = Date.now();
    $('audio-status').textContent = `使用：${media.getTracks()[0].label || '麥克風'}。請說一句完整的話，並稍作停頓。`;
  } catch (error) {
    notice(`無法啟動麥克風：${error.message}。請確認瀏覽器權限，並使用 localhost 或 127.0.0.1。`);
    await stopCapture();
  }
}
function startCapture() {
  if (state !== 'idle' || navigating || !session) return;
  if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
    notice('請使用最新版 Chrome 或 Edge，並以 http://127.0.0.1:8000 開啟。'); return;
  }
  notice(); setState('preparing');
  inputFrames = receivedSeconds = 0; inputRms = 0; hasRecognizedText = false;
  lastAudioAt = Date.now();
  const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/sessions/${session.id}/audio`);
  ws = socket;
  socket.onmessage = (event) => {
    if (ws !== socket) return;
    const data = JSON.parse(event.data);
    if (data.type === 'ready' && state === 'preparing') {
      threshold = data.threshold ?? .003; configureSensitivity(); setupAudio(socket);
    }
    if (data.type === 'configured') threshold = data.threshold;
    if (data.type === 'audio') {
      receivedSeconds = data.received_seconds;
      if (state === 'recording' && inputRms >= threshold) $('audio-status').textContent = `服務已收到 ${receivedSeconds.toFixed(1)} 秒音訊 · ${data.processing ? '正在辨識，請稍候' : '已偵測到聲音'}`;
    }
    if (data.type === 'recognizing' && state === 'recording') {
      $('recording-detail').textContent = data.final ? '已偵測停頓，正在確認這段字幕。' : '已收到聲音，正在產生暫定字幕；第一次推論可能較久。';
    }
    if (data.type === 'segment') {
      upsert(data.segment);
      if (data.segment.text) hasRecognizedText = true;
      if (data.segment.status === 'committed' && !data.segment.text && !hasRecognizedText) {
        $('audio-status').textContent = '有收到音訊，但模型尚未辨識出文字。請確認選對麥克風、靠近說話，再試一個完整句子。';
      }
    }
    if (data.type === 'error') { notice(data.message); stopCapture(); }
    if (data.type === 'stopped') { releaseAudio(); setState('idle','字幕與錄音已保存，可在設定與紀錄回放或下載。'); refreshRecordings().catch(error=>notice(error.message)); }
  };
  socket.onerror = () => notice('連線失敗。請確認本機服務仍在執行。');
  socket.onclose = () => {
    if (ws !== socket) return;
    if (state === 'recording' || state === 'preparing') notice('連線已中斷，麥克風已停止。已辨識的文字仍保留於本機。');
    releaseAudio(); ws = null; setState('idle');
  };
}
$('start').onclick = startCapture;
$('stop').onclick = stopCapture;
$('new-session').onclick = () => newSession().catch(error => notice(error.message));
$('export').onclick = () => {
  if (drafts.size) { notice('請先儲存或取消編輯，再匯出。'); return; }
  const anchor = node('a'); anchor.href = `/api/sessions/${session.id}/export/${$('export-format').value}`;
  anchor.download = ''; anchor.click();
};
window.addEventListener('beforeunload', event => {
  if (drafts.size || glossaryDirty || savingEdits() || state !== 'idle') { event.preventDefault(); event.returnValue = ''; }
});
// Recover updates completed after a disconnected page and show corrections
// from another tab. upsert preserves open drafts and ignores older revisions.
setInterval(async () => {
  if (!session || state !== 'idle' || polling || navigating) return;
  polling = true;
  const sid = session.id;
  try {
    const data = await api(`/api/sessions/${sid}`);
    if (session?.id === sid && state === 'idle' && !navigating) {
      for (const row of data.segments) upsert(row);
      renderRecordings(data.recordings);
    }
  } catch { /* Keep the saved view usable during a brief server restart. */ }
  finally { polling = false; }
}, 3000);
try {
  await refreshMicrophones().catch(() => {});
  await loadGlossary();
  const health = await api('/api/health'); $('model').textContent = `${health.label || 'Whisper'} ${health.model} · ${health.device.toUpperCase()}`;
  const rows = await loadSessions(), stored = localStorage.getItem('caption-session');
  if (rows.length) await openSession(rows.some(r => r.id === stored) ? stored : rows[0].id);
  else await newSession();
} catch (error) { notice(error.message); }
