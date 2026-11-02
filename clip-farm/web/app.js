'use strict';
const $ = id => document.getElementById(id);
let config, current = null, job = null, filter = 'all', uploading = false, starting = false, active = false, galleryKey = '', previewIndex = null, polling = false;
let video = null, chat = null, sourceMode = 'local';
const text = (tag, value, cls) => { const el = document.createElement(tag); el.textContent = value; if (cls) el.className = cls; return el; };
function error(message) { $('message').textContent = message; $('message').hidden = !message; }
let toastTimer;
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 4000); }
async function api(path, body) {
  const response = await fetch(path, { method: body === undefined ? 'GET' : 'POST', cache: 'no-store',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json', 'X-Studio-Token': config.token },
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(15000) });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'The request could not be completed.');
  return data;
}
function enableRun() {
  $('run').disabled = !config?.ffmpeg || !(sourceMode === 'url' ? $('vodUrl').value.trim() : video) || uploading || starting || active;
  $('run').firstElementChild.textContent = uploading ? 'Uploading your file…' : active ? 'A run is processing…' : starting ? 'Starting…' : 'Find my highlights';
}
function renderSource() {
  $('videoName').textContent = video?.name || 'Drop your VOD here';
  $('videoHint').textContent = video ? (video.size / 1024 / 1024).toFixed(1) + ' MB · click to replace' : 'or browse files';
  $('chatName').textContent = chat?.name || '';
  $('clearChat').hidden = !chat;
  enableRun();
}
function upload(file, kind) {
  if (!file || !config) return;
  if (uploading) { error('Please wait for the current upload to finish.'); return; }
  const allowed = kind === 'video' ? /\.(mp4|mkv|mov|webm|avi|m4v)$/i : /\.csv$/i;
  if (!allowed.test(file.name)) { error(kind === 'video' ? 'Choose an MP4, MKV, MOV, WebM, AVI or M4V recording.' : 'Choose a CSV chat file with a time_seconds column.'); return; }
  if (!file.size || file.size > (kind === 'video' ? 8 * 1024 ** 3 : 20 * 1024 ** 2)) { error('Upload limit: 8 GB for video, 20 MB for chat. Empty files cannot be processed.'); return; }
  error(''); uploading = true; enableRun();
  const status = $('uploadStatus'); status.hidden = false; $('uploadProgress').value = 0;
  status.lastElementChild.textContent = 'Uploading ' + file.name;
  const request = new XMLHttpRequest(); request.open('PUT', '/api/upload/' + kind); request.timeout = 30 * 60 * 1000;
  request.setRequestHeader('Content-Type', 'application/octet-stream');
  request.setRequestHeader('X-Studio-Token', config.token); request.setRequestHeader('X-File-Name', encodeURIComponent(file.name));
  request.upload.onprogress = event => { if (event.lengthComputable) { const pct = Math.round(event.loaded / event.total * 100); $('uploadProgress').value = pct; status.lastElementChild.textContent = `Uploading ${file.name} · ${pct}%`; } };
  const finish = () => { uploading = false; status.hidden = true; renderSource(); };
  request.onload = () => {
    try { const result = JSON.parse(request.responseText); if (request.status !== 200) throw Error(result.error || 'Upload failed.');
      if (kind === 'video') video = result; else chat = result;
      try { sessionStorage.setItem('clipDraft', JSON.stringify({ video, chat })); } catch {}
      toast(kind === 'video' ? 'Recording ready. Set your cut and run.' : 'Chat activity added.');
    } catch (exc) { error(exc.message); } finally { finish(); }
  };
  request.onerror = request.ontimeout = () => { error('Upload interrupted. Check that Clip Studio is running, then choose the file again.'); finish(); };
  request.send(file);
}
$('videoFile').onchange = event => upload(event.target.files[0], 'video');
$('chatFile').onchange = event => upload(event.target.files[0], 'chat');
$('dropzone').onkeydown = event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); $('videoFile').click(); } };
for (const name of ['dragenter', 'dragover']) $('dropzone').addEventListener(name, event => { event.preventDefault(); $('dropzone').classList.add('dragover'); });
for (const name of ['dragleave', 'drop']) $('dropzone').addEventListener(name, event => { event.preventDefault(); $('dropzone').classList.remove('dragover'); });
$('dropzone').addEventListener('drop', event => { if (event.dataTransfer.files.length !== 1) error('Drop one recording at a time.'); else upload(event.dataTransfer.files[0], 'video'); });
// Prevent a misplaced drop from navigating away from a running job.
window.addEventListener('dragover', event => event.preventDefault()); window.addEventListener('drop', event => event.preventDefault());
$('clearChat').onclick = () => { chat = null; $('chatFile').value = ''; try { sessionStorage.setItem('clipDraft', JSON.stringify({ video, chat })); } catch {} renderSource(); };
function chooseSource(mode) {
  sourceMode = mode; $('urlNotice').hidden = mode !== 'url'; $('dropzone').hidden = mode !== 'local';
  $('localTab').classList.toggle('selected', mode === 'local'); $('urlTab').classList.toggle('selected', mode === 'url'); enableRun();
}
$('urlTab').onclick = () => chooseSource('url');
$('localTab').onclick = () => chooseSource('local');
$('vodUrl').oninput = enableRun;
$('duration').oninput = () => { $('durationLabel').textContent = $('duration').value + ' sec'; };
$('less').onclick = () => { $('top').value = Math.max(1, (Number($('top').value) || 1) - 1); };
$('more').onclick = () => { $('top').value = Math.min(100, (Number($('top').value) || 1) + 1); };
$('captions').onchange = () => { $('modelWrap').hidden = !$('captions').checked; };
$('run').onclick = async () => {
  if ($('run').disabled) return;
  if (!$('top').checkValidity() || !$('top').value) { $('top').reportValidity(); return; }
  if (sourceMode === 'url' && !$('vodUrl').checkValidity()) { $('vodUrl').reportValidity(); return; }
  error(''); starting = true; enableRun();
  try {
    try { sessionStorage.setItem('clipSettings', JSON.stringify({ top: Number($('top').value), duration: Number($('duration').value), layout: document.querySelector('[name=layout]:checked').value, captions: $('captions').checked, model: $('model').value })); } catch {}
    const result = await api('/api/runs', { video: sourceMode === 'local' ? video?.id : undefined, url: sourceMode === 'url' ? $('vodUrl').value.trim() : undefined, chat: chat?.id, top: Number($('top').value),
      duration: Number($('duration').value), layout: document.querySelector('[name=layout]:checked').value,
      captions: $('captions').checked, model: $('model').value });
    current = result.id; galleryKey = ''; active = true; await refresh();
    $('resultsAnchor')?.scrollIntoView({ behavior: 'smooth' });
  } catch (exc) { error(exc.message); } finally { starting = false; enableRun(); }
};
function clock(seconds) { const value = Math.max(0, Math.floor(seconds)); return Math.floor(value / 60) + ':' + String(value % 60).padStart(2, '0'); }
function friendlyDate(value) { return new Date(value).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }); }
async function selectRun(id) {
  current = id; galleryKey = ''; filter = 'all'; error('');
  try { const data = await api('/api/runs/' + id); if (current === id) { job = data; renderJob(); } } catch (exc) { error(exc.message); }
  document.querySelectorAll('.history-item').forEach(b => b.classList.toggle('selected', b.dataset.id === id));
}
function renderHistory(rows) {
  active = rows.some(row => row.status === 'running'); enableRun();
  const history = $('history'); history.replaceChildren();
  if (!rows.length) { history.append(text('p', 'No runs yet. Your first cut starts here.', 'muted')); return; }
  for (const row of rows) {
    const b = text('button', '', 'history-item' + (row.id === current ? ' selected' : '')); b.dataset.id = row.id;
    b.append(text('strong', row.name), text('small', friendlyDate(row.created) + ' · ' + row.status));
    b.onclick = () => selectRun(row.id); history.append(b);
  }
}
function renderJob() {
  $('empty').hidden = true; $('processing').hidden = false; $('openFolder').hidden = !job.folder;
  $('runTitle').textContent = job.name; $('phase').textContent = job.phase;
  $('statusBadge').textContent = job.status === 'complete' ? 'READY TO REVIEW' : job.status.toUpperCase();
  $('elapsed').textContent = job.status === 'running' ? clock((Date.now() - Date.parse(job.created)) / 1000) + ' elapsed' : friendlyDate(job.created);
  $('phaseNote').textContent = job.status === 'complete' ? 'Your clips are ready. Preview, check the captions, and choose your keepers.' :
    job.status === 'running' ? 'Working on this PC. Stage updates appear below; rendering and transcription can take a while.' : 'Your source is unchanged. Check the log, adjust the settings, and start a new run.';
  $('activityBar').className = 'activity-bar' + (job.status === 'complete' ? ' done' : job.status === 'running' ? '' : ' failed');
  const log = $('logs'), bottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
  log.textContent = job.logs.join('\n') || 'Waiting for the pipeline…'; if (bottom) log.scrollTop = log.scrollHeight;
  if (job.status === 'failed' || job.status === 'interrupted') $('logDetails').open = true;
  $('reviewSection').hidden = job.status !== 'complete';
  if (job.status === 'complete') {
    const key = job.id + JSON.stringify(job.reviews) + filter;
    if (key !== galleryKey) { renderGallery(); galleryKey = key; }
  }
}
function reviewButtons(clip) {
  const group = text('div', '', 'clip-actions');
  for (const [decision, label, cls] of [['approved', '✓ Approve', 'approve'], ['rejected', '× Reject', 'reject']]) {
    const b = text('button', clip.review === decision ? (decision === 'approved' ? '✓ Approved' : '× Rejected') : label, cls);
    b.setAttribute('aria-pressed', String(clip.review === decision));
    b.onclick = async () => {
      const id = job.id; group.querySelectorAll('button').forEach(x => x.disabled = true);
      try { const result = await api(`/api/runs/${id}/${clip.index}/review`, { decision: clip.review === decision ? 'pending' : decision });
        if (job.id === id) { clip.review = result.review; job.reviews[String(clip.index)] = result.review; galleryKey = ''; renderJob(); if ($('preview').open && previewIndex === clip.index) renderPreviewActions(clip); }
        toast(result.review === 'approved' ? 'Copied to approved. Your original stays safe.' : result.review === 'rejected' ? 'Rejected. Original kept in this run.' : 'Moved back to your review queue.');
      } catch (exc) { error(exc.message); group.querySelectorAll('button').forEach(x => x.disabled = false); }
    }; group.append(b);
  } return group;
}
function captionPlain(value) { return value.split(/\r?\n/).filter(line => !/^\d+$/.test(line.trim()) && !line.includes('-->')).join('\n').trim(); }
function renderGallery() {
  $('clipCount').textContent = String(job.clips.length).padStart(2, '0');
  const formats = [...new Set(job.clips.map(c => `${c.width} × ${c.height}`))].join(', ');
  $('resultNote').textContent = `${job.clips.length} of ${job.requested_top} requested clips · ${formats}` + (job.clips.length < job.requested_top ? ' · Fewer distinct, non-overlapping peaks were available.' : ' · Ranked by audio and chat activity.');
  document.querySelectorAll('[data-filter]').forEach(b => b.classList.toggle('selected', b.dataset.filter === filter));
  $('gallery').replaceChildren();
  const clips = job.clips.filter(c => filter === 'all' || c.review === filter); $('filterEmpty').hidden = clips.length > 0;
  for (const clip of clips) {
    const card = text('article', '', 'clip-card ' + clip.review); card.dataset.index = clip.index;
    const screen = text('button', '', 'clip-screen'); screen.setAttribute('aria-label', 'Preview highlight ' + (clip.index + 1));
    const video = document.createElement('video'); video.src = clip.url + '#t=0.1'; video.preload = 'metadata'; video.muted = true; video.playsInline = true; video.tabIndex = -1;
    const play = text('span', '', 'play'); play.append(text('b', '▶'));
    screen.append(video, play, text('span', 'HIGHLIGHT ' + String(clip.index + 1).padStart(2, '0'), 'clip-number'), text('span', clock(clip.actual_duration), 'duration'));
    screen.onclick = () => preview(clip);
    const info = text('div', '', 'clip-info'), heading = text('h4', 'Highlight ' + String(clip.index + 1).padStart(2, '0'));
    heading.append(text('span', Math.round(clip.score * 100) + ' / 100', 'score'));
    const snippet = captionPlain(clip.caption_text);
    info.append(heading, text('p', `${clock(clip.start)} – ${clock(clip.end)} in source · ${clip.caption_cues || 0} caption cues`),
      text('p', snippet ? snippet.replace(/\s+/g, ' ').slice(0, 110) + (snippet.length > 110 ? '…' : '') : 'No speech captions for this clip.'), reviewButtons(clip));
    card.append(screen, info); $('gallery').append(card);
  }
}
function renderPreviewActions(clip) { $('previewActions').replaceChildren(reviewButtons(clip)); }
function preview(clip) {
  previewIndex = clip.index; $('previewTitle').textContent = 'Highlight ' + String(clip.index + 1).padStart(2, '0');
  $('previewScore').textContent = `ACTIVITY ${Math.round(clip.score * 100)}/100 · AUDIO ${Math.round(clip.audio_score * 100)} · CHAT ${Math.round(clip.chat_score * 100)}`;
  $('previewVideo').src = clip.url; $('previewCaptions').textContent = clip.caption_text || 'No captions were generated for this clip.';
  renderPreviewActions(clip); $('preview').showModal();
}
$('closePreview').onclick = () => $('preview').close();
$('preview').addEventListener('close', () => { $('previewVideo').pause(); $('previewVideo').removeAttribute('src'); $('previewVideo').load(); previewIndex = null; });
document.querySelectorAll('[data-filter]').forEach(b => b.onclick = () => { filter = b.dataset.filter; galleryKey = ''; renderJob(); });
$('openFolder').onclick = async () => { try { await api('/api/runs/' + current + '/open', {}); toast('Opened the run folder.'); } catch (exc) { error(exc.message); } };
$('newRun').onclick = () => { current = null; job = null; galleryKey = ''; error(''); $('empty').hidden = false; $('processing').hidden = true; $('reviewSection').hidden = true; $('openFolder').hidden = true; $('runTitle').textContent = 'From recording to ready.'; document.querySelectorAll('.history-item').forEach(b => b.classList.remove('selected')); $('videoFile').focus(); };
$('refreshHistory').onclick = () => refresh();
$('historyToggle').onclick = () => { document.querySelector('.sidebar').classList.toggle('history-open'); $('history').scrollIntoView({ block: 'nearest' }); };
async function refresh(initial = false) {
  if (polling || !config) return; polling = true;
  try {
    const rows = await api('/api/runs'); renderHistory(rows);
    $('connection').textContent = '● Local engine connected'; $('connection').classList.remove('error');
    if (initial && rows.length) current = rows.find(r => r.status === 'running')?.id || rows[0].id;
    if (current) { const id = current; const data = await api('/api/runs/' + id); if (current === id) { job = data; renderJob(); } }
  } catch (exc) { $('connection').textContent = 'Engine disconnected'; $('connection').classList.add('error'); error('Cannot reach Clip Studio. Keep its terminal open, then refresh. ' + exc.message); }
  finally { polling = false; }
}
async function init() {
  try {
    config = await api('/api/config');
    $('outputPath').textContent = 'OUTPUT · ' + config.output;
    const models = config.models.length ? config.models : [{ name: 'tiny.en (must be cached locally)', path: 'tiny.en' }];
    for (const model of models) { const option = text('option', model.name); option.value = model.path; $('model').append(option); }
    try {
      const saved = JSON.parse(sessionStorage.getItem('clipSettings') || '{}');
      if (Number.isInteger(saved.top) && saved.top >= 1 && saved.top <= 100) $('top').value = saved.top;
      if (Number.isInteger(saved.duration) && saved.duration >= 15 && saved.duration <= 60) $('duration').value = saved.duration;
      if (['blur', 'crop'].includes(saved.layout)) document.querySelector(`[name=layout][value=${saved.layout}]`).checked = true;
      if (typeof saved.captions === 'boolean') $('captions').checked = saved.captions;
      if (models.some(m => m.path === saved.model)) $('model').value = saved.model;
      $('duration').oninput(); $('captions').onchange();
    } catch {}
    if (!config.ffmpeg) error('FFmpeg or ffprobe is missing from PATH. Set up the existing CLI before rendering. No installation was attempted.');
    try { const draft = JSON.parse(sessionStorage.getItem('clipDraft') || '{}'); video = draft.video || null; chat = draft.chat || null; } catch {}
    renderSource(); await refresh(true); setInterval(refresh, 1200);
  } catch (exc) { error('Could not connect to the local engine: ' + exc.message); $('connection').textContent = 'Engine unavailable'; $('connection').classList.add('error'); }
}
init();
