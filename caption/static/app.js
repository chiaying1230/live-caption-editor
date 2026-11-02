const $ = (id) => document.getElementById(id);
const labels = {provisional: '暫定', committed: 'AI 確認', human_corrected: '人工校正 · 已鎖定'};
let session = null, segments = new Map(), cards = new Map(), drafts = new Set();
let state = 'idle', ws = null, context = null, media = null, source = null, processor = null, sink = null;
let flushResolve = null;
let polling = false;
let navigating = false;
let inputFrames = 0, lastAudioAt = 0, recordingSince = 0, inputRms = 0, threshold = .003;
let receivedSeconds = 0, hasRecognizedText = false;

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
  $('new-session').disabled = state !== 'idle' || navigating;
  $('export').disabled = !session || !segments.size || drafts.size > 0 || navigating;
  $('export').title = drafts.size ? '請先儲存或取消編輯，再匯出' : '';
  $('signal').classList.toggle('live', state === 'recording');
  $('microphone').disabled = state !== 'idle';
  for (const button of $('sessions').children) button.disabled = state !== 'idle' || navigating;
  $('count').textContent = `${segments.size} 段`;
  $('empty').hidden = segments.size > 0;
}
function setState(next, detail) {
  state = next;
  $('recording-status').textContent = {idle:'準備就緒',preparing:'準備模型與麥克風',recording:'正在收音',stopping:'收音已停止，正在完成辨識'}[next];
  $('recording-detail').textContent = detail || {idle:'按下開始收音，允許使用麥克風。',preparing:'首次使用需要下載模型，請保持連線。',recording:'暫定字幕會持續更新；稍作停頓後即可編輯。',stopping:'最後一段音訊處理完成後，會保留在逐字稿。'}[next];
  updateControls();
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
  segments.set(row.id, row);
  let card = cards.get(row.id);
  if (!card) {
    card = node('article', 'segment');
    card.dataset.id = row.id;
    const meta = node('div', 'segment-meta');
    meta.append(node('span', 'badge'), node('time'));
    const body = node('div', 'segment-body');
    body.append(node('p', 'segment-text'));
    const edit = node('button', 'edit-trigger', '編輯文字 ↗');
    edit.addEventListener('click', () => editSegment(row.id));
    body.append(edit);
    card.append(meta, body);
    cards.set(row.id, card);
    $('segments').append(card);
  }
  card.className = `segment ${row.status}`;
  card.querySelector('.badge').textContent = labels[row.status];
  card.querySelector('time').textContent = `${time(row.start)} — ${time(row.end)}`;
  card.querySelector('.segment-text').textContent = row.text || (row.status === 'provisional' ? '正在辨識…' : '（未辨識到文字，可人工補上）');
  card.querySelector('.edit-trigger').hidden = row.status === 'provisional' || drafts.has(row.id);
  updateControls();
}
function editSegment(id) {
  if (drafts.has(id)) return;
  const row = segments.get(id), card = cards.get(id), body = card.querySelector('.segment-body');
  const revision = row.revision;
  drafts.add(id);
  body.querySelector('.segment-text').hidden = true;
  body.querySelector('.edit-trigger').hidden = true;
  const form = node('form', 'editor'), input = node('textarea');
  input.value = row.text;
  input.maxLength = 20000;
  input.setAttribute('aria-label', `編輯 ${time(row.start)} 的字幕`);
  const actions = node('div', 'edit-actions'), save = node('button','primary save','儲存並鎖定');
  save.type = 'submit';
  const cancel = node('button','secondary cancel','取消');
  cancel.type = 'button';
  actions.append(save, cancel, node('small', '', 'Ctrl + Enter 儲存 · Esc 取消'));
  form.append(input, actions);
  body.append(form);
  const close = () => {
    drafts.delete(id); form.remove(); body.querySelector('.segment-text').hidden = false;
    upsert(segments.get(id));
  };
  cancel.onclick = close;
  form.onsubmit = async (event) => {
    event.preventDefault(); save.disabled = cancel.disabled = true;
    try {
      const updated = await api(`/api/sessions/${session.id}/segments/${id}`, {method:'PATCH',body:JSON.stringify({text:input.value,revision})});
      upsert(updated); close(); notice();
    } catch (error) { notice(error.message + ' 你的輸入仍保留在編輯框。'); }
    finally { save.disabled = cancel.disabled = false; }
  };
  input.onkeydown = (event) => {
    if (event.isComposing) return;
    if (event.ctrlKey && event.key === 'Enter') { event.preventDefault(); form.requestSubmit(); }
    if (event.key === 'Escape' && !cancel.disabled) close();
  };
  input.focus(); updateControls();
}
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
  if (state !== 'idle' || navigating) return;
  if (drafts.size) { notice('請先儲存或取消編輯，再切換聽打。'); return; }
  navigating = true; updateControls();
  try { await selectSession(id); }
  finally { navigating = false; updateControls(); }
}
async function selectSession(id) {
  const data = await api(`/api/sessions/${id}`);
  session = data.session;
  localStorage.setItem('caption-session', session.id);
  $('title').textContent = session.title;
  segments.clear(); cards.clear(); $('segments').replaceChildren();
  for (const row of data.segments) upsert(row);
  await loadSessions(); updateControls();
  notice(data.recording ? '這場聽打仍在其他頁面收音或處理中；請先在原頁面停止。' : data.segments.some(r => r.status === 'provisional') ? '有上次中斷留下的暫定字幕，尚未經 AI 確認；TXT 與 JSON 匯出會保留並標示。' : '');
}
async function newSession() {
  if (state !== 'idle' || navigating) return;
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
    if (data.type === 'stopped') { releaseAudio(); setState('idle','辨識已完成。文字已存入本機，可繼續校正或匯出。'); }
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
  if (drafts.size || state !== 'idle') { event.preventDefault(); event.returnValue = ''; }
});
// Recover updates completed after a disconnected page and show corrections
// from another tab. upsert preserves open drafts and ignores older revisions.
setInterval(async () => {
  if (!session || state !== 'idle' || polling || navigating) return;
  polling = true;
  const sid = session.id;
  try {
    const data = await api(`/api/sessions/${sid}`);
    if (session?.id === sid && state === 'idle' && !navigating) for (const row of data.segments) upsert(row);
  } catch { /* Keep the saved view usable during a brief server restart. */ }
  finally { polling = false; }
}, 3000);
try {
  await refreshMicrophones().catch(() => {});
  const health = await api('/api/health'); $('model').textContent = `${health.label || 'Whisper'} ${health.model} · ${health.device.toUpperCase()}`;
  const rows = await loadSessions(), stored = localStorage.getItem('caption-session');
  if (rows.length) await openSession(rows.some(r => r.id === stored) ? stored : rows[0].id);
  else await newSession();
} catch (error) { notice(error.message); }
