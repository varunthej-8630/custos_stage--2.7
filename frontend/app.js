const socket = io({
  reconnection: true,
  reconnectionAttempts: Infinity,
  reconnectionDelay: 1000,
  reconnectionDelayMax: 5000,
  timeout: 10000,
});
let alertsData = [], dismissed = false, monitoring = false;
let drawMode = false, zoneType = 'HIGH', zones = [], drawing = false, sx, sy, cx, cy;
let t0 = Date.now(), peakRisk = 0, rHist = [], aPerHr = new Array(24).fill(0);
let rChart = null, aChart = null, curPage = 'dashboard', afilt = 'all';
let selCamIdx = 0, availCams = [];
// Real camera frame dimensions — received from server on first socket update
let camW = 640, camH = 480, camDimsReady = false;

// ═══════════════════════════════════════════════════════
// CAMERA MODAL
// How it works:
//   1. User clicks "📷 Camera" button
//   2. Browser calls /list_cameras on Python server
//   3. Python probes cv2.VideoCapture(0..4) — only real cameras appear
//   4. Results shown as cards — laptop cam + any USB cams connected
//   5. User selects one and clicks Apply
//   6. socket.emit('set_camera') tells Python to switch cv2 source
//   7. Feed reloads with new camera
// ═══════════════════════════════════════════════════════
async function openCamModal() {
  // Show modal immediately with spinner
  document.getElementById('camOverlay').classList.add('on');
  document.getElementById('camApply').disabled = true;
  document.getElementById('camSub').textContent = 'Scanning connected cameras…';
  document.getElementById('camNote').textContent = 'Python is probing OpenCV camera indices 0–4';
  document.getElementById('camList').innerHTML =
    '<div class="cam-scan-msg"><div class="cam-spinner"></div>Scanning, please wait…</div>';

  availCams = [];

  try {
    // Ask Python backend to scan cameras using OpenCV
    const response = await fetch('/list_cameras');
    const data = await response.json();

    if (!data.cameras || data.cameras.length === 0) {
      // No cameras found at all
      document.getElementById('camList').innerHTML =
        '<div class="cam-error-box">⚠ No cameras detected. Check your connections and try again.</div>';
      document.getElementById('camSub').textContent = 'No cameras found';
      document.getElementById('camNote').textContent = 'Connect a camera and click the Camera button again';
      return;
    }

    availCams = data.cameras;
    const count = availCams.length;
    document.getElementById('camSub').textContent =
      count === 1 ? '1 camera detected' : `${count} cameras detected`;
    document.getElementById('camNote').textContent =
      'Select a camera below and click Apply to switch';

    renderCamList();

  } catch (err) {
    document.getElementById('camList').innerHTML =
      '<div class="cam-error-box">⚠ Could not reach server. Is Python running?</div>';
    document.getElementById('camSub').textContent = 'Server connection failed';
    document.getElementById('camNote').textContent = 'Make sure python web_server.py is running';
  }
}

function renderCamList() {
  document.getElementById('camList').innerHTML = availCams.map(cam => `
    <div class="cam-item ${cam.index === selCamIdx ? 'sel' : ''}" onclick="selectCam(${cam.index})">
      <div class="cam-ico">${cam.icon}</div>
      <div class="cam-info">
        <div class="cam-name">${cam.name}</div>
        <div class="cam-sub-text">${cam.sub}</div>
      </div>
      <div class="cam-chk">${cam.index === selCamIdx ? '✓' : ''}</div>
    </div>
  `).join('');
  document.getElementById('camApply').disabled = false;
}

function selectCam(idx) {
  selCamIdx = idx;
  renderCamList();
}

function confirmCam() {
  const cam = availCams.find(c => c.index === selCamIdx);
  if (!cam) return;

  // Tell Python to switch the cv2.VideoCapture source
  socket.emit('set_camera', { index: selCamIdx });

  // Update HUD and settings labels immediately
  document.getElementById('hudCam').textContent = `CAM-0${selCamIdx + 1}`;
  document.getElementById('setCam').textContent = `${cam.name} (Index ${selCamIdx})`;

  // Reload the MJPEG feed so it shows the new camera
  const feed = document.getElementById('liveFeed');
  feed.src = '/video_feed?t=' + Date.now();

  document.getElementById('camOverlay').classList.remove('on');
}

// Close modal when clicking outside
document.getElementById('camOverlay').addEventListener('click', function (e) {
  if (e.target === this) this.classList.remove('on');
});

// ═══════════════════════════════════════════════════════
// SOCKET — with reconnection and connection status
// ═══════════════════════════════════════════════════════
let vizMode = 'USER'; // 'USER', 'SECURITY', 'DEBUG'
function setVizMode(m) {
  vizMode = m;
  ['btnVmUser', 'btnVmSec', 'btnVmDbg'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.toggle('sel', (id === 'btnVmUser' && m === 'USER') || (id === 'btnVmSec' && m === 'SECURITY') || (id === 'btnVmDbg' && m === 'DEBUG'));
  });
}

function onHealthUpdate(h) {
  const el = document.getElementById('sysHealthBox');
  if (el) {
    el.innerHTML = `
      <div style="font-size:11px;font-family:var(--mono);color:var(--txt3);display:flex;gap:12px;align-items:center;">
        <span>⚡ Latency: <strong>${h.inference_latency_ms || 0}ms</strong></span>
        <span>🖥 CPU: <strong>${h.cpu_usage_pct || 0}%</strong></span>
        <span>💾 RAM: <strong>${h.ram_usage_gb || 0}GB</strong></span>
        <span>📹 Cam: <strong style="color:${h.camera && h.camera.connected ? 'var(--green)' : 'var(--red)'}">${h.camera ? h.camera.status : 'ONLINE'}</strong></span>
        <span>📥 Queue: <strong>${h.queue_depths ? (h.queue_depths.CaptureQueue || 0) : 0}</strong></span>
      </div>`;
  }
}

socket.on('connect', () => { console.log('[CUSTOS] connected'); setConnStatus(true); });
socket.on('disconnect', () => { console.log('[CUSTOS] disconnected'); setConnStatus(false); });
socket.on('connect_error', () => setConnStatus(false));
socket.on('risk_update', onUpdate);
socket.on('system_health', onHealthUpdate);

socket.on('tamper', d => {
  showBanner('CAMERA TAMPER DETECTED', 'Camera obstructed at ' + d.time);
  playAlertSound('tamper');
  alertsData.unshift({ time: d.time, score: 100, events: ['CAMERA TAMPERED!'], snapshot: '', clip: d.clip || '', resolved: false });
  renderTl(alertsData.slice(0, 8)); renderAlertsList(); refreshEvIfOpen();
  document.getElementById('notifPip').classList.add('on');
});
socket.on('alert_resolved', () => {
  const a = alertsData.find(x => !x.resolved); if (a) a.resolved = true;
  renderTl(alertsData.slice(0, 8)); renderAlertsList();
  dismissed = false;
  const b = document.getElementById('alertBanner');
  if (b.classList.contains('on')) {
    b.style.background = 'var(--green-bg)'; b.style.borderBottomColor = 'rgba(34,197,94,0.2)';
    document.getElementById('abTitle').style.color = 'var(--green)';
    document.getElementById('abTitle').textContent = 'Alert Resolved — Person Left Zone';
    document.getElementById('abSub').textContent = 'Risk returning to safe level';
    document.getElementById('abIcon').textContent = '✓';
    document.getElementById('abIcon').style.background = 'var(--green)';
    setTimeout(() => { b.classList.remove('on'); b.style = ''; }, 4000);
  }
});
function setConnStatus(ok) {
  // Sidebar connection pip — green when live, amber when reconnecting
  const pip = document.querySelector('.s-pip.on');
  const lbl = document.querySelector('.sb-status span');
  if (pip) pip.style.background = ok ? '' : 'var(--amber)';
  if (lbl) lbl.style.color = ok ? '' : 'var(--amber)';
}

// ═══════════════════════════════════════════════════════
// NAVIGATION
// ═══════════════════════════════════════════════════════
function gotoPage(p) {
  document.querySelectorAll('.page').forEach(x => x.classList.remove('on'));
  document.querySelectorAll('.ni').forEach(x => x.classList.remove('on'));
  document.getElementById('page-' + p).classList.add('on');
  document.getElementById('ni-' + p).classList.add('on');
  curPage = p;
  if (p === 'analytics') initCharts();
  if (p === 'evidence') loadEvidence();
  if (p === 'alerts') renderAlertsList();
}
let slim = false;
function toggleSb() {
  slim = !slim;
  document.getElementById('sidebar').classList.toggle('slim', slim);
  document.getElementById('sbToggle').textContent = slim ? '▶' : '◀';
}

// ═══════════════════════════════════════════════════════
// MAIN UPDATE
// ═══════════════════════════════════════════════════════
function onUpdate(d) {
  // Capture real camera dims from server on first update
  if (d.cam_w && d.cam_h && !camDimsReady) {
    camW = d.cam_w; camH = d.cam_h; camDimsReady = true;
    console.log(`[CUSTOS] Camera: ${camW}×${camH}`);
  }
  const score = d.score || 0;
  rHist.push({ t: new Date().toTimeString().slice(0, 5), v: score });
  if (rHist.length > 60) rHist.shift();
  if (score > peakRisk) peakRisk = score;

  let col, lbl, lvc, dotc, bc;
  if (score < 40) { col = '#22c55e'; lbl = 'SAFE'; lvc = 'lv-safe'; dotc = ''; bc = 'safe'; }
  else if (score < 60) { col = '#f59e0b'; lbl = 'WATCH'; lvc = 'lv-watch'; dotc = 'w'; bc = 'watch'; }
  else if (score < 80) { col = '#f97316'; lbl = 'SUSPICIOUS'; lvc = 'lv-sus'; dotc = 's'; bc = 'sus'; }
  else { col = '#ef4444'; lbl = 'CRITICAL'; lvc = 'lv-crit'; dotc = 'c'; bc = 'crit'; }

  ['riskNum', 'monRiskNum'].forEach(id => { const e = document.getElementById(id); if (e) { e.textContent = Math.round(score); e.style.color = col; } });
  ['riskFill', 'monRiskFill'].forEach(id => { const e = document.getElementById(id); if (e) { e.style.width = score + '%'; e.style.background = col; } });
  ['riskBadge', 'monBadge'].forEach(id => { const e = document.getElementById(id); if (e) { e.className = 'risk-badge ' + bc; e.textContent = '● ' + lbl; } });
  const lp = document.getElementById('levelPill'); lp.className = 'level-pill ' + lvc; lp.textContent = '● ' + lbl;
  document.getElementById('riskDot').className = 'risk-ind ' + dotc;
  if (d.mode) document.getElementById('modeTag').textContent = d.mode + ' MODE';

  const active = {};
  (d.event_log || []).forEach(e => {
    if (e.includes('PACING')) active.PACING = true;
    if (e.includes('CROUCH')) active.CROUCHING = true;
    if (e.includes('linger')) active.LINGERING = true;
    if (e.includes('FROZE')) active.FREEZE = true;
    if (e.includes('RUNNING')) active.RUNNING = true;
    if (e.includes('circling')) active.CIRCLING = true;
  });
  const bHtml = ['PACING', 'CROUCHING', 'LINGERING', 'FREEZE', 'RUNNING', 'CIRCLING']
    .map(k => `<span class="chip ${active[k] ? 'active' : ''}">${k}</span>`).join('');
  ['behChips', 'monBeh'].forEach(id => { const e = document.getElementById(id); if (e) e.innerHTML = bHtml; });

  const reasons = getRs(d.event_log || []);
  const wp = document.getElementById('whyPanel');
  if (d.situation_briefing) {
    const sb = d.situation_briefing;
    wp.innerHTML = `
      <div style="padding:10px 12px;background:var(--bg);border-radius:var(--r);border:1px solid var(--border);margin-bottom:10px;">
        <div style="font-size:10px;font-weight:800;color:var(--txt3);text-transform:uppercase;letter-spacing:1px;margin-bottom:3px;">Situational Report</div>
        <div style="font-size:12px;font-weight:600;color:var(--txt);margin-bottom:4px;">${sb.summary}</div>
        <div style="font-size:11px;color:var(--blue);font-weight:700;">💡 ${sb.recommended_action}</div>
      </div>` + (reasons.length ? reasons.map(r => `<div class="why-row on"><div class="why-pip on"></div>${r}</div>`).join('') : '');
  } else {
    wp.innerHTML = reasons.length
      ? reasons.map(r => `<div class="why-row on"><div class="why-pip on"></div>${r}</div>`).join('')
      : '<div class="empty-msg">No active alerts</div>';
  }


  if (d.alert_active && !dismissed) {
    const isH = (d.event_log || []).some(e => e.includes('HIGH'));
    showBanner(isH ? 'HIGH ZONE BREACH — Person Detected' : 'SUSPICIOUS ACTIVITY DETECTED',
      (reasons[0] || 'Suspicious activity') + ' · Score: ' + Math.round(score));
    document.getElementById('notifPip').classList.add('on');
    maybePlayAlert(true, false);
  } else if (!d.alert_active) {
    dismissed = false;
    maybePlayAlert(false, d.tamper || false);
  }
  if (d.tamper) maybePlayAlert(false, true);

  if (d.alerts && d.alerts.length) {
    alertsData = d.alerts; const n = d.alerts.length;
    document.getElementById('stAlerts').textContent = n;
    document.getElementById('tlCount').textContent = n + (n !== 1 ? ' alerts' : ' alert');
    const unresolved = d.alerts.filter(a => !a.resolved).length;
    const b = document.getElementById('alertBadge'); b.textContent = unresolved; b.style.display = unresolved ? 'block' : 'none';
    d.alerts.forEach(a => { const h = parseInt((a.time || '0').split(':')[0]); if (!isNaN(h)) aPerHr[h]++; });
    renderTl(d.alerts.slice(0, 8));
    if (curPage === 'alerts') renderAlertsList();
  }
  document.getElementById('stPersons').textContent = d.persons || 0;
  document.getElementById('hudFps').textContent = (d.fps || 0) + ' FPS';
  document.getElementById('hudPersons').textContent = (d.persons || 0) + ' persons';
  document.getElementById('monFps').textContent = (d.fps || 0) + ' FPS';
  document.getElementById('anTotal').textContent = alertsData.length;
  document.getElementById('anHigh').textContent = alertsData.filter(a => (a.events || []).some(e => e.includes('HIGH'))).length;
  document.getElementById('anPeak').textContent = peakRisk > 0 ? Math.round(peakRisk) : '—';
  const avg = alertsData.length ? Math.round(alertsData.reduce((s, a) => s + (a.score || 0), 0) / alertsData.length) : 0;
  document.getElementById('anAvg').textContent = avg;
  if (curPage === 'analytics') updateCharts();
  document.getElementById('stZones').textContent = zones.length;
  document.getElementById('setZones').textContent = zones.length;
}

function getRs(evts) {
  const o = [];
  evts.forEach(e => {
    if (e.includes('entered HIGH')) o.push('Person entered restricted area');
    else if (e.includes('PACING')) o.push('Person pacing back and forth');
    else if (e.includes('CROUCH')) o.push('Person crouching in zone');
    else if (e.includes('FROZE')) o.push('Person froze suddenly');
    else if (e.includes('circling')) o.push('Person repeatedly returning');
    else if (e.includes('linger')) o.push('Person lingering too long');
    else if (e.includes('RUNNING')) o.push('Person running in zone');
    else if (e.includes('TAMPER')) o.push('Camera tamper detected');
  });
  return [...new Set(o)];
}

function renderTl(alerts) {
  const el = document.getElementById('dashTl');
  if (!alerts.length) { el.innerHTML = '<div class="empty-msg">No alerts yet</div>'; return; }
  el.innerHTML = alerts.map((a, i) => {
    const isH = (a.events || []).some(e => e.includes('HIGH')), isT = (a.events || []).some(e => e.includes('TAMPER'));
    const desc = getRs(a.events || [])[0] || 'Suspicious activity', tl = isT ? 'TAMPER' : isH ? 'HIGH' : 'OBS';
    const isR = a.resolved;
    return `<div class="tl-item ${isH || isT ? '' : 'obs'}" onclick="openEvidence(${i})" style="${isR ? 'opacity:0.7' : ''}">
      <div class="tl-top"><span class="tl-type ${isH || isT ? 'h' : 'o'}" style="${isR ? 'background:var(--green-bg);color:var(--green)' : ''}">${isR ? '✓ ' + tl : tl}</span><span class="tl-time">${a.time}</span></div>
      <div class="tl-desc">${desc}</div>
      <div class="tl-score">Score <em>${a.score}</em></div>
    </div>`;
  }).join('');
}

function showBanner(t, s) { document.getElementById('abTitle').textContent = t; document.getElementById('abSub').textContent = s; document.getElementById('alertBanner').classList.add('on'); }
function dismissBanner() { dismissed = true; document.getElementById('alertBanner').classList.remove('on'); }
function demoAlert() {
  playAlertSound('alert');
  showBanner('HIGH ZONE BREACH — DEMO', 'Risk Score: 100 · Demo mode');
  ['riskNum', 'monRiskNum'].forEach(id => { const e = document.getElementById(id); if (e) { e.textContent = '100'; e.style.color = '#ef4444'; } });
  ['riskFill', 'monRiskFill'].forEach(id => { const e = document.getElementById(id); if (e) { e.style.width = '100%'; e.style.background = '#ef4444'; } });
  ['riskBadge', 'monBadge'].forEach(id => { const e = document.getElementById(id); if (e) { e.className = 'risk-badge crit'; e.textContent = '● CRITICAL'; } });
  document.getElementById('levelPill').className = 'level-pill lv-crit';
  document.getElementById('levelPill').textContent = '● CRITICAL';
  document.getElementById('riskDot').className = 'risk-ind c';
  document.getElementById('notifPip').classList.add('on');
}
function demoTamper() { playAlertSound('tamper'); showBanner('CAMERA TAMPER DETECTED — DEMO', 'Obstruction simulated · ' + new Date().toTimeString().slice(0, 8)); }

function filterAlerts(f, btn) {
  afilt = f; document.querySelectorAll('.fbt').forEach(b => b.classList.remove('sel')); btn.classList.add('sel'); renderAlertsList();
}
function renderAlertsList() {
  const el = document.getElementById('alertsList');
  let data = alertsData;
  if (afilt !== 'all') data = data.filter(a => {
    const ev = a.events || [];
    if (afilt === 'RESOLVED') return a.resolved;
    if (afilt === 'HIGH') return ev.some(e => e.includes('HIGH'));
    if (afilt === 'TAMPER') return ev.some(e => e.includes('TAMPER'));
    if (afilt === 'OBSERVATION') return !ev.some(e => e.includes('HIGH') || e.includes('TAMPER'));
    return true;
  });
  if (!data.length) { el.innerHTML = '<div class="empty-msg" style="padding:60px 0;">No alerts match this filter</div>'; return; }
  el.innerHTML = data.map(a => {
    const isH = (a.events || []).some(e => e.includes('HIGH')), isT = (a.events || []).some(e => e.includes('TAMPER'));
    const reasons = getRs(a.events || []), tl = isT ? 'TAMPER' : isH ? 'HIGH' : 'OBSERVATION', idx = alertsData.indexOf(a);
    return `<div class="alert-card ${isT ? 'tamper' : isH ? '' : 'obs'}">
      <div class="ac-top">
        <div class="ac-meta"><div class="ac-type ${isH || isT ? '' : 'o'}">${tl} — ${isT ? 'Camera Tampered' : isH ? 'Intrusion' : 'Suspicious Behaviour'}</div><div class="ac-desc">${reasons[0] || 'Suspicious activity detected'}</div></div>
        <div class="ac-time">${a.time}</div><div class="ac-score">${a.score}</div>
      </div>
      <div class="ac-bot">
        <div class="ac-tags">${reasons.map(r => `<span class="ac-tag">${r}</span>`).join('')}</div>
        <button class="view-ev" onclick="openEvidence(${idx})">View Evidence</button>
      </div>
    </div>`;
  }).join('');
}

function fmtTs(raw) {
  const m = raw.match(/(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);
  if (!m) return raw;
  let h = parseInt(m[4]); const min = m[5], sec = m[6], ap = h >= 12 ? 'PM' : 'AM'; h = h % 12 || 12;
  return `${m[3]}/${m[2]}/${m[1]} ${h}:${min}:${sec} ${ap}`;
}
function refreshEvIfOpen() { if (curPage === 'evidence') loadEvidence(); }
async function loadEvidence() {
  const g = document.getElementById('evGrid'); g.innerHTML = '<div class="ev-empty">Loading…</div>';
  try {
    const r = await fetch('/list_evidence'); const d = await r.json();
    if (!d.files || !d.files.length) { g.innerHTML = '<div class="ev-empty">No evidence yet — alerts auto-save here</div>'; return; }
    const clips = d.files.filter(f => f.name.endsWith('.mp4'));
    const images = d.files.filter(f => !f.name.endsWith('.mp4'));
    const rc = f => {
      const isT = f.name.includes('pretamper'), isV = f.name.endsWith('.mp4');
      const badge = isT ? 'tamper' : 'alert', bt = isT ? 'TAMPER' : 'ALERT';
      const thumb = isV
        ? `<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:28px;background:var(--bg2)">🎬</div>`
        : `<img src="/snapshots/${f.name}?t=${Date.now()}" style="width:100%;height:100%;object-fit:cover;" onerror="this.parentElement.innerHTML='<div style=width:100%;height:100%;display:flex;align-items:center;justify-content:center;background:var(--bg2);font-size:28px>📷</div>'">`;
      const ts = fmtTs(f.name.replace(/^(alert_|pretamper_)/, '').replace(/\.(jpg|mp4)$/, ''));
      return `<div class="ev-card" onclick="openFile('${f.name}')">
        <div class="ev-thumb">${thumb}<div class="ev-play">${isV ? '▶' : '🔍'}</div><span class="ev-badge ${badge}">${bt}</span></div>
        <div class="ev-info"><div class="ev-name">${isT ? 'Tamper Clip' : 'Alert Snapshot'}</div><div class="ev-ts">${ts}</div></div>
      </div>`;
    };
    g.innerHTML = `<div class="ev-sect">🎬 Video Clips (${clips.length})</div>${clips.length ? clips.map(rc).join('') : '<div class="ev-empty" style="grid-column:1/-1;padding:12px 0;">No clips yet</div>'}<div class="ev-sect">📷 Alert Snapshots (${images.length})</div>${images.length ? images.map(rc).join('') : '<div class="ev-empty" style="grid-column:1/-1;padding:12px 0;">No snapshots yet</div>'}`;
  } catch (e) { g.innerHTML = '<div class="ev-empty">Could not load — server starting up</div>'; }
}
function openEvidence(idx) {
  const a = alertsData[idx]; if (!a) return;
  const isT = (a.events || []).some(e => e.includes('TAMPER'));
  if (isT && a.clip) openFile(a.clip); else if (a.snapshot) openFile(a.snapshot);
  else { document.getElementById('modalBg').classList.add('on'); showMErr(); }
}
function openFile(fname) {
  const bg = document.getElementById('modalBg'), img = document.getElementById('mImg'), vid = document.getElementById('mVid'), err = document.getElementById('mErr');
  bg.classList.add('on'); img.style.display = 'none'; vid.style.display = 'none'; err.style.display = 'none';
  document.getElementById('mMeta').textContent = fname;
  if (fname.endsWith('.mp4')) {
    document.getElementById('modalTitle').textContent = 'Tamper Video Clip';
    vid.style.display = 'block';
    vid.src = '/snapshots/' + fname;
    vid.onerror = function() {
      vid.style.display = 'none';
      err.style.display = 'block';
      err.innerHTML = `<div style="font-size:28px;margin-bottom:12px;">🎬</div><div style="font-size:13px;font-weight:600;color:var(--txt);margin-bottom:6px;">${fname}</div><div style="font-size:11px;color:var(--txt3);margin-bottom:18px;">Playback issue — click below to download</div><a href="/snapshots/${fname}" download="${fname}" style="font-size:12px;font-weight:700;padding:10px 22px;border-radius:12px;border:2px solid var(--blue);color:var(--blue);text-decoration:none;background:var(--blue-bg);">⬇ Download Clip</a>`;
    };
    vid.play().catch(e => console.log('Autoplay deferred:', e));
  } else { document.getElementById('modalTitle').textContent = 'Alert Snapshot'; img.style.display = 'block'; img.src = '/snapshots/' + fname + '?t=' + Date.now(); }
}
function showMErr() { document.getElementById('mImg').style.display = 'none'; document.getElementById('mVid').style.display = 'none'; document.getElementById('mErr').style.display = 'block'; }
function closeModal() { document.getElementById('modalBg').classList.remove('on'); try { document.getElementById('mVid').pause(); } catch(e){} document.getElementById('mImg').src = ''; document.getElementById('mVid').src = ''; }

// ═══════════════════════════════════════════════════════
// CHARTS
// ═══════════════════════════════════════════════════════
const cOpts = { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { backgroundColor: '#fff', titleColor: '#1a2236', bodyColor: '#4a5568', titleFont: { family: 'Barlow Condensed', size: 12, weight: '800' }, bodyFont: { family: 'DM Mono', size: 11 }, borderColor: 'rgba(0,0,0,0.08)', borderWidth: 1, padding: 10 } }, scales: { x: { grid: { color: 'rgba(0,0,0,0.04)' }, ticks: { color: '#8a96a8', font: { family: 'DM Mono', size: 9 } } }, y: { grid: { color: 'rgba(0,0,0,0.04)' }, ticks: { color: '#8a96a8', font: { family: 'DM Mono', size: 9 } } } } };
function initCharts() {
  if (rChart && aChart) { updateCharts(); return; }
  rChart = new Chart(document.getElementById('riskChart'), { type: 'line', data: { labels: [], datasets: [{ data: [], fill: true, borderColor: '#3b7ff5', borderWidth: 2.5, backgroundColor: 'rgba(59,127,245,0.08)', pointRadius: 3, pointBackgroundColor: '#3b7ff5', tension: 0.4 }] }, options: { ...cOpts, scales: { x: { ...cOpts.scales.x }, y: { ...cOpts.scales.y, min: 0, max: 100 } } } });
  aChart = new Chart(document.getElementById('alertChart'), { type: 'bar', data: { labels: Array.from({ length: 24 }, (_, i) => i + ':00'), datasets: [{ data: new Array(24).fill(0), backgroundColor: 'rgba(239,68,68,0.2)', borderColor: '#ef4444', borderWidth: 2, borderRadius: 6 }] }, options: cOpts });
  updateCharts();
}
function updateCharts() {
  if (!rChart || !aChart) return;
  const l = rHist.slice(-30); rChart.data.labels = l.map(p => p.t); rChart.data.datasets[0].data = l.map(p => p.v); rChart.update('none');
  aChart.data.datasets[0].data = [...aPerHr]; aChart.update('none');
}

// ═══════════════════════════════════════════════════════
// ZONE DRAWING
// KEY FIX: Uses real camera frame size from server (camW/camH)
// instead of feedEl.naturalWidth — which returns 0 on MJPEG streams.
// Letterbox offsets computed correctly for object-fit:contain layout.
// ═══════════════════════════════════════════════════════
const canvas = document.getElementById('zoneCanvas'), ctx = canvas.getContext('2d');
const feedEl = document.getElementById('liveFeed'), fa = document.getElementById('feedArea');

function resizeCanvas() { canvas.width = fa.clientWidth; canvas.height = fa.clientHeight; redraw(); }
window.addEventListener('resize', resizeCanvas);
feedEl.addEventListener('load', () => { setTimeout(resizeCanvas, 100); });
setTimeout(resizeCanvas, 300); setTimeout(resizeCanvas, 900);

function toggleDraw() {
  drawMode = !drawMode; const b = document.getElementById('btnDraw'), r = document.getElementById('ztRow');
  b.textContent = drawMode ? 'Drawing…' : 'Draw Zone'; b.classList.toggle('drawing', drawMode);
  r.classList.toggle('on', drawMode); canvas.classList.toggle('draw', drawMode); fa.classList.toggle('cross', drawMode);
}
function setZT(t) {
  zoneType = t;
  document.getElementById('ztHigh').className = 'zt' + (t === 'HIGH' ? ' high' : '');
  document.getElementById('ztObs').className = 'zt' + (t === 'OBSERVATION' ? ' obs' : '');
}
canvas.addEventListener('mousedown', e => {
  if (!drawMode) return;
  const r = canvas.getBoundingClientRect();
  sx = e.clientX - r.left; sy = e.clientY - r.top;
  drawing = true;
});
canvas.addEventListener('mousemove', e => {
  if (!drawing) return;
  const r = canvas.getBoundingClientRect();
  cx = e.clientX - r.left; cy = e.clientY - r.top;
  redraw(); prevZone();
});
canvas.addEventListener('mouseup', e => {
  if (!drawing) return;
  drawing = false;
  const r = canvas.getBoundingClientRect();
  cx = e.clientX - r.left; cy = e.clientY - r.top;
  if (Math.abs(cx - sx) > 20 && Math.abs(cy - sy) > 20) {
    zones.push({ x1: Math.min(sx, cx), y1: Math.min(sy, cy), x2: Math.max(sx, cx), y2: Math.max(sy, cy), type: zoneType });
    document.getElementById('stZones').textContent = zones.length;
    document.getElementById('zbStat').textContent = zones.length + ' zone(s) drawn';
    redraw(); sendZones();
  }
});
function redraw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  zones.forEach((z, i) => {
    const isH = z.type === 'HIGH', col = isH ? '#ef4444' : '#f97316';
    ctx.fillStyle = isH ? 'rgba(239,68,68,0.13)' : 'rgba(249,115,22,0.13)';
    ctx.fillRect(z.x1, z.y1, z.x2 - z.x1, z.y2 - z.y1);
    ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.strokeRect(z.x1, z.y1, z.x2 - z.x1, z.y2 - z.y1);
    ctx.lineWidth = 3; const L = 12;
    [[z.x1, z.y1, 1, 1], [z.x2, z.y1, -1, 1], [z.x1, z.y2, 1, -1], [z.x2, z.y2, -1, -1]].forEach(([px, py, dx, dy]) => {
      ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(px + dx * L, py); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(px, py + dy * L); ctx.stroke();
    });
    ctx.fillStyle = col; ctx.font = '700 12px Barlow Condensed,sans-serif';
    const lbl = `Z${i + 1} ${z.type}`, tw = ctx.measureText(lbl).width;
    ctx.beginPath(); ctx.roundRect(z.x1, z.y1 - 22, tw + 16, 22, 6); ctx.fill();
    ctx.fillStyle = '#fff'; ctx.fillText(lbl, z.x1 + 8, z.y1 - 6);
  });
}
function prevZone() {
  // FIX: call redraw() first so ghost zones don't accumulate while dragging
  redraw();
  const col = zoneType === 'HIGH' ? '#ef4444' : '#f97316';
  ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.setLineDash([6, 4]);
  ctx.strokeRect(sx, sy, cx - sx, cy - sy); ctx.setLineDash([]);
  ctx.fillStyle = zoneType === 'HIGH' ? 'rgba(239,68,68,0.07)' : 'rgba(249,115,22,0.07)';
  ctx.fillRect(sx, sy, cx - sx, cy - sy);
}
function clearZones() {
  zones = []; ctx.clearRect(0, 0, canvas.width, canvas.height);
  document.getElementById('stZones').textContent = '0';
  document.getElementById('zbStat').textContent = 'Draw zones then start';
  sendZones(false);
}

// ── COORDINATE MAPPING ──────────────────────────────────
// Feed uses object-fit:contain → compute letterbox offsets.
// camW/camH = real camera frame dimensions from server.
// Canvas pixel → camera pixel: subtract letterbox offset, then scale.
function getLetterbox() {
  const cW = canvas.width, cH = canvas.height;
  const ar = camW / camH, bar = cW / cH;
  let rW, rH, oX, oY;
  if (ar > bar) { rW = cW; rH = cW / ar; oX = 0; oY = (cH - rH) / 2; }
  else { rH = cH; rW = cH * ar; oX = (cW - rW) / 2; oY = 0; }
  return { rW, rH, oX, oY };
}
function sendZones(mon) {
  if (mon === undefined) mon = monitoring;
  const { rW, rH, oX, oY } = getLetterbox();
  const scX = camW / rW, scY = camH / rH;
  const sc = zones.map(z => {
    // The feed is CSS-flipped (scaleX(-1)) but Python sees the real unflipped frame.
    // Mirror the canvas X coords before sending so zones align with Python's frame.
    const rx1 = canvas.width - z.x2, rx2 = canvas.width - z.x1;
    return [
      Math.max(0, Math.round((rx1 - oX) * scX)),
      Math.max(0, Math.round((z.y1 - oY) * scY)),
      Math.min(camW, Math.round((rx2 - oX) * scX)),
      Math.min(camH, Math.round((z.y2 - oY) * scY))
    ];
  });
  socket.emit('set_zones', { zones: sc, types: zones.map(z => z.type === 'HIGH' ? 'HIGH' : 'WATCH'), monitoring: mon });
}
function startMonitoring() {
  if (!zones.length) { document.getElementById('zbStat').textContent = '⚠ Draw a zone first'; return; }
  monitoring = true; sendZones(true);
  const b = document.getElementById('btnStart'); b.textContent = '■ Active'; b.classList.add('active');
  document.getElementById('zbStat').textContent = 'AI detection running';
  if (drawMode) toggleDraw();
}
function feedErr() { document.getElementById('feedOffline').classList.add('on'); }
function feedOk() {
  document.getElementById('feedOffline').classList.remove('on');
  // Fallback: grab natural dims if server hasn't sent them yet
  if (!camDimsReady && feedEl.naturalWidth > 0) {
    camW = feedEl.naturalWidth; camH = feedEl.naturalHeight; camDimsReady = true;
  }
}
function tick() {
  const t = new Date().toTimeString().slice(0, 8);
  document.getElementById('topClock').textContent = t;
  document.getElementById('hudClock').textContent = t;
  const s = Math.floor((Date.now() - t0) / 1000), m = Math.floor(s / 60), h = Math.floor(m / 60);
  document.getElementById('stUptime').textContent = h > 0 ? h + 'h ' + (m % 60) + 'm' : m + 'm';
}
setInterval(tick, 1000); tick();

// ═══════════════════════════════════════════════════════
// ALERT SOUND — Web Audio API (no file needed)
// Two sounds: sharp alert beep for intrusions, lower tone for tamper
// ═══════════════════════════════════════════════════════
let audioCtx = null;
function getAudioCtx() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  return audioCtx;
}

function playAlertSound(type = 'alert') {
  try {
    const ctx = getAudioCtx();
    const now = ctx.currentTime;

    if (type === 'alert') {
      // Three sharp rising beeps — urgent, attention-grabbing
      [0, 0.22, 0.44].forEach((offset, i) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain); gain.connect(ctx.destination);
        osc.type = 'square';
        osc.frequency.setValueAtTime(880 + i * 220, now + offset);
        gain.gain.setValueAtTime(0, now + offset);
        gain.gain.linearRampToValueAtTime(0.35, now + offset + 0.01);
        gain.gain.exponentialRampToValueAtTime(0.001, now + offset + 0.18);
        osc.start(now + offset);
        osc.stop(now + offset + 0.2);
      });
    } else if (type === 'tamper') {
      // Low pulsing tone — different from alert so you know it's tamper
      [0, 0.3, 0.6].forEach(offset => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain); gain.connect(ctx.destination);
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(220, now + offset);
        gain.gain.setValueAtTime(0, now + offset);
        gain.gain.linearRampToValueAtTime(0.3, now + offset + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.001, now + offset + 0.25);
        osc.start(now + offset);
        osc.stop(now + offset + 0.28);
      });
    }
  } catch (e) {
    console.warn('[SOUND] Audio error:', e);
  }
}

// Track last alert state to avoid repeating sound every socket tick
let _lastAlertState = false;

// ═══════════════════════════════════════════════════════
// ═══════════════════════════════════════════════════════
// EVIDENCE INTELLIGENCE CENTER (CENTRALIZED REACTIVE STATE ENGINE)
// ═══════════════════════════════════════════════════════
const state = {
  incidents: [],
  filteredIncidents: [],
  selectedIncident: null,
  mode: "all", // "user" | "security" | "all"
  filters: {
    q: "",
    subject_id: "",
    camera_id: "",
    zone: "",
    min_reliability: 0,
    start_date: "",
    end_date: "",
    incident_type: ""
  },
  replay: {
    isPlaying: false,
    currentStep: 0,
    timer: null
  },
  loading: false,
  error: null
};

let filterDebounceTimer = null;

function logState(action) {
  console.log(`[CUSTOS STATE: ${action}]`, {
    mode: state.mode,
    filters: { ...state.filters },
    selectedIncident: state.selectedIncident ? state.selectedIncident.id : null,
    replayStep: state.replay.currentStep,
    loading: state.loading,
    error: state.error,
    incidentsCount: state.incidents.length,
    filteredCount: state.filteredIncidents.length
  });
}

function onFilterInput() {
  if (filterDebounceTimer) clearTimeout(filterDebounceTimer);
  filterDebounceTimer = setTimeout(() => {
    applyFilters();
  }, 300);
}

function setMode(modeName) {
  state.mode = modeName;
  ['btnVmUser', 'btnVmSec', 'btnVmAll'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      const isSel = (id === 'btnVmUser' && modeName === 'user') ||
                    (id === 'btnVmSec' && modeName === 'security') ||
                    (id === 'btnVmAll' && modeName === 'all');
      el.classList.toggle('sel', isSel);
    }
  });
  logState("setMode: " + modeName);
  fetchIncidents();
}

function setVizMode(m) {
  if (m === 'USER') setMode('user');
  else if (m === 'SECURITY') setMode('security');
  else setMode('all');
}

function getEventsList(item) {
  if (!item || !item.events) return [];
  if (Array.isArray(item.events)) return item.events;
  if (typeof item.events === 'string') {
    try {
      const p = JSON.parse(item.events);
      if (Array.isArray(p)) return p;
    } catch(e) {}
    return [item.events];
  }
  return [];
}

function readFiltersFromDOM() {
  state.filters.q = (document.getElementById('evSearchQuery')?.value || '').trim();
  state.filters.subject_id = (document.getElementById('evFilterSubject')?.value || '').trim();
  state.filters.camera_id = document.getElementById('evFilterCamera')?.value || '';
  state.filters.zone = document.getElementById('evFilterZone')?.value || '';
  state.filters.min_reliability = parseFloat(document.getElementById('evFilterReliability')?.value || '0');
  state.filters.start_date = document.getElementById('evFilterStartDate')?.value || '';
  state.filters.end_date = document.getElementById('evFilterEndDate')?.value || '';
  state.filters.incident_type = document.getElementById('evFilterIncidentType')?.value || '';
}

async function fetchIncidents() {
  state.loading = true;
  state.error = null;
  renderIncidents();

  readFiltersFromDOM();

  const params = new URLSearchParams();
  if (state.mode && state.mode !== 'all') params.append('mode', state.mode);
  if (state.filters.q) params.append('q', state.filters.q);
  if (state.filters.subject_id) params.append('subject_id', state.filters.subject_id);
  if (state.filters.camera_id !== '') params.append('camera_id', state.filters.camera_id);
  if (state.filters.zone) params.append('zone', state.filters.zone);
  if (state.filters.min_reliability > 0) params.append('min_reliability', state.filters.min_reliability);
  if (state.filters.start_date) params.append('start_date', state.filters.start_date);
  if (state.filters.end_date) params.append('end_date', state.filters.end_date);
  if (state.filters.incident_type) params.append('incident_type', state.filters.incident_type);

  try {
    const r = await fetch('/api/incidents?' + params.toString());
    if (!r.ok) throw new Error(`HTTP error ${r.status}`);
    const data = await r.json();
    state.incidents = data || [];
    state.filteredIncidents = [...state.incidents];
    state.loading = false;
    logState("fetchIncidents: success");
    renderIncidents();

    if (state.filteredIncidents.length > 0) {
      if (!state.selectedIncident || !state.filteredIncidents.find(x => x.id === state.selectedIncident.id)) {
        selectEvidenceCard(0);
      } else {
        renderEvidencePreview(state.selectedIncident);
      }
    } else {
      state.selectedIncident = null;
      renderEvidencePreview(null);
    }
  } catch(err) {
    console.error('[EVIDENCE] Fetch Error:', err);
    state.loading = false;
    state.error = err.message || 'Unable to load evidence.';
    logState("fetchIncidents: error");
    showError(state.error);
  }
}

function loadEvidenceIntelligence() {
  fetchIncidents();
}

function applyFilters() {
  fetchIncidents();
}

function applyEvidenceFilters() {
  fetchIncidents();
}

function resetFilters() {
  state.filters = {
    q: "",
    subject_id: "",
    camera_id: "",
    zone: "",
    min_reliability: 0,
    start_date: "",
    end_date: "",
    incident_type: ""
  };
  ['evSearchQuery', 'evFilterSubject', 'evFilterCamera', 'evFilterZone', 'evFilterReliability', 'evFilterStartDate', 'evFilterEndDate', 'evFilterIncidentType'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  logState("resetFilters");
  fetchIncidents();
}

function showError(msg) {
  const container = document.getElementById('evCardsContainer');
  if (container) {
    container.innerHTML = `
      <div style="padding:20px;background:var(--red-bg);border:1px solid rgba(239,68,68,0.2);border-radius:var(--r);text-align:center;">
        <div style="font-size:24px;margin-bottom:8px;">⚠️</div>
        <div style="font-size:13px;font-weight:700;color:var(--red);margin-bottom:6px;">Unable to load evidence</div>
        <div style="font-size:11px;color:var(--txt2);margin-bottom:12px;">${msg}</div>
        <button class="zb danger" onclick="fetchIncidents()">Retry Connection</button>
      </div>`;
  }
}

socket.on('evidence_alert', pkg => {
  state.incidents.unshift(pkg);
  state.filteredIncidents.unshift(pkg);
  logState("socket: evidence_alert");
  if (curPage === 'evidence') {
    renderIncidents();
  }
});

function renderIncidents() {
  const container = document.getElementById('evCardsContainer');
  const countEl = document.getElementById('evRecordCount');
  if (countEl) countEl.textContent = `${state.filteredIncidents ? state.filteredIncidents.length : 0} records`;
  if (!container) return;

  if (state.loading) {
    container.innerHTML = `
      <div class="skeleton-card"><div class="skeleton-line short"></div><div class="skeleton-line mid"></div><div class="skeleton-line"></div></div>
      <div class="skeleton-card"><div class="skeleton-line short"></div><div class="skeleton-line mid"></div><div class="skeleton-line"></div></div>
      <div class="skeleton-card"><div class="skeleton-line short"></div><div class="skeleton-line mid"></div><div class="skeleton-line"></div></div>`;
    return;
  }

  if (state.error) {
    showError(state.error);
    return;
  }

  const items = state.filteredIncidents;
  if (!items || !items.length) {
    container.innerHTML = `
      <div class="ev-empty" style="padding:40px 16px;text-align:center;">
        <div style="font-size:28px;margin-bottom:8px;">🔎</div>
        <div style="font-size:13px;font-weight:700;color:var(--txt);margin-bottom:4px;">No incidents found</div>
        <div style="font-size:11px;color:var(--txt3);">No records match your active search or filter criteria.</div>
      </div>`;
    return;
  }

  container.innerHTML = items.map((item, idx) => {
    const score = item.score || 0;
    const rel = item.reliability_score || 100;
    const scoreCol = score < 40 ? 'var(--green)' : score < 70 ? 'var(--amber)' : 'var(--red)';
    const relCol = rel >= 80 ? 'var(--green)' : rel >= 50 ? 'var(--amber)' : 'var(--red)';
    const isSel = state.selectedIncident && (state.selectedIncident.id === item.id || state.selectedIncident.timestamp === item.timestamp);
    const ts = item.timestamp ? new Date(item.timestamp).toLocaleTimeString() : 'Recent';
    const evList = getEventsList(item);
    const snapThumb = item.snapshot_path ? `/snapshots/${item.snapshot_path}` : '';

    return `
      <div onclick="selectEvidenceCard(${idx})" style="padding:12px 14px;background:${isSel ? 'var(--blue-bg)' : 'var(--bg)'};border:2px solid ${isSel ? 'var(--blue)' : 'var(--border)'};border-radius:var(--r);cursor:pointer;transition:all 0.15s;display:flex;gap:12px;align-items:center;">
        ${snapThumb ? `<div style="width:54px;height:54px;border-radius:8px;overflow:hidden;flex-shrink:0;background:#000;"><img src="${snapThumb}" style="width:100%;height:100%;object-fit:cover;" onerror="this.parentElement.style.display='none'"></div>` : ''}
        <div style="flex:1;min-width:0;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
            <strong style="font-size:13px;color:var(--txt);">${item.subject_id || 'Person-Track'}</strong>
            <span style="font-size:10px;font-family:var(--mono);color:var(--txt3);">${ts}</span>
          </div>
          <div style="display:flex;gap:6px;align-items:center;margin-bottom:4px;flex-wrap:wrap;">
            <span class="chip" style="background:${scoreCol};color:#fff;font-weight:800;font-size:10px;">Risk ${Math.round(score)}</span>
            <span class="chip" style="background:${relCol};color:#fff;font-weight:800;font-size:10px;">Reliability ${Math.round(rel)}%</span>
            <span style="font-size:10px;color:var(--txt2);font-weight:600;">Cam ${item.camera_id ?? 0}</span>
            <span style="font-size:10px;color:var(--txt2);font-weight:600;">Zone: ${item.zone_name || 'Main'}</span>
          </div>
          <div style="font-size:11px;color:var(--txt3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
            ${evList.join(' · ') || 'Detection Event'}
          </div>
        </div>
      </div>`;
  }).join('');
}

function renderEvidenceCards(items) {
  if (items) state.filteredIncidents = items;
  renderIncidents();
}

function selectEvidenceCard(idx) {
  state.selectedIncident = state.filteredIncidents[idx] || null;
  logState("selectEvidenceCard: " + idx);
  renderIncidents();
  renderEvidencePreview(state.selectedIncident);
}

function getTimeline(item) {
  if (!item) return [];
  const raw = item.timeline || item.timeline_json || [];
  if (Array.isArray(raw)) return raw;
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed;
    } catch(e) {}
  }
  return [];
}

function renderEvidencePreview(item) {
  const container = document.getElementById('evPreviewContent');
  if (!container) return;
  if (!item) {
    container.innerHTML = '<div class="empty-msg" style="padding:40px 0;">Select an evidence card to preview details and replay timeline</div>';
    return;
  }

  const snapshotUrl = item.snapshot_path ? `/snapshots/${item.snapshot_path}` : '';
  const clipUrl = item.clip_path ? `/snapshots/${item.clip_path}` : '';
  const timeline = getTimeline(item);

  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:12px;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div style="font-size:14px;font-weight:800;color:var(--txt);">Incident Details · ${item.subject_id || 'Subject'}</div>
        <span class="chip" style="background:var(--blue-bg);color:var(--blue);font-weight:700;">Cam ${item.camera_id ?? 0}</span>
      </div>
      
      ${snapshotUrl ? `<div style="width:100%;border-radius:var(--r);overflow:hidden;border:1px solid var(--border);"><img src="${snapshotUrl}" style="width:100%;display:block;" onerror="this.parentElement.style.display='none'"></div>` : ''}
      ${clipUrl ? `<div style="width:100%;border-radius:var(--r);overflow:hidden;border:1px solid var(--border);"><video id="replayVideo" src="${clipUrl}" controls style="width:100%;display:block;"></video></div>` : ''}

      <!-- AI INCIDENT BRIEFING -->
      <div style="padding:12px;background:var(--bg);border-radius:var(--r);border:1px solid var(--border);">
        <div style="font-size:10px;font-weight:800;color:var(--txt3);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;">AI Incident Briefing</div>
        <div style="font-size:13px;font-weight:700;color:var(--txt);margin-bottom:6px;">${item.ai_summary || getEventsList(item).join(' · ')}</div>
        <div style="font-size:11px;color:var(--blue);font-weight:700;margin-bottom:8px;">💡 Recommended Action: ${item.recommended_action || 'Continue active monitoring.'}</div>
        <div style="font-size:11px;color:var(--txt2);line-height:1.5;">
          <strong>Threat Analysis:</strong> Risk Score: ${Math.round(item.score || 0)} | Reliability: ${Math.round(item.reliability_score || 100)}% | Zone: ${item.zone_name || 'Observation'} | Dwell: ${item.subject_dwell_time || 0}s | Status: ${item.status || 'New'}
        </div>
      </div>

      <!-- INCIDENT REPLAY CONTROLLER -->
      <div style="padding:12px;background:var(--bg);border-radius:var(--r);border:1px solid var(--border);">
        <div style="font-size:11px;font-weight:800;color:var(--txt);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">▶ Interactive Incident Replay</div>
        <div id="replayTimelineBox" style="font-size:11px;color:var(--txt2);margin-bottom:10px;min-height:40px;"></div>
        <div style="display:flex;gap:6px;">
          <button class="zb" id="btnPlay" onclick="playReplay()">▶ Play</button>
          <button class="zb" id="btnPause" onclick="pauseReplay()">❚❚ Pause</button>
          <button class="zb" id="btnPrev" onclick="previousFrame()">⏪ Prev</button>
          <button class="zb" id="btnNext" onclick="nextFrame()">⏩ Next</button>
        </div>
      </div>
    </div>`;

  state.replay.currentStep = 0;
  pauseReplay();
  renderReplayStep(timeline);
}

function renderReplayStep(timeline) {
  const box = document.getElementById('replayTimelineBox');
  if (!box || !timeline || !timeline.length) {
    if (box) box.innerHTML = '<div class="empty-msg">No timeline steps available</div>';
    return;
  }
  const total = timeline.length;
  state.replay.currentStep = ((state.replay.currentStep % total) + total) % total;
  const step = timeline[state.replay.currentStep];
  
  box.innerHTML = `
    <div style="padding:8px 10px;background:var(--white);border-radius:var(--r);border:1.5px solid var(--blue);">
      <div style="display:flex;justify-content:space-between;margin-bottom:2px;">
        <strong style="color:var(--blue);font-weight:800;">Step ${step.step || state.replay.currentStep + 1} of ${total}</strong>
        <span style="font-family:var(--mono);font-size:10px;color:var(--txt3);">${step.time || ''}</span>
      </div>
      <div style="font-size:12px;font-weight:600;color:var(--txt);">${step.action || step}</div>
    </div>`;
  logState("renderReplayStep: " + state.replay.currentStep);
}

function playReplay() {
  pauseReplay();
  state.replay.isPlaying = true;
  const timeline = getTimeline(state.selectedIncident);
  if (!timeline.length) return;
  logState("playReplay");

  state.replay.timer = setInterval(() => {
    state.replay.currentStep++;
    renderReplayStep(timeline);
  }, 1500);
}

function startReplay() {
  playReplay();
}

function pauseReplay() {
  state.replay.isPlaying = false;
  if (state.replay.timer) {
    clearInterval(state.replay.timer);
    state.replay.timer = null;
  }
  logState("pauseReplay");
}

function nextFrame() {
  pauseReplay();
  const timeline = getTimeline(state.selectedIncident);
  if (!timeline.length) return;
  state.replay.currentStep++;
  renderReplayStep(timeline);
}

function previousFrame() {
  pauseReplay();
  const timeline = getTimeline(state.selectedIncident);
  if (!timeline.length) return;
  state.replay.currentStep--;
  renderReplayStep(timeline);
}

function stepReplay(dir) {
  if (dir > 0) nextFrame();
  else previousFrame();
}

function seekTimeline(stepIndex) {
  pauseReplay();
  state.replay.currentStep = stepIndex;
  const timeline = getTimeline(state.selectedIncident);
  renderReplayStep(timeline);
}

// Global page initializer hook
const _origGotoPage = window.gotoPage;
window.gotoPage = function(p) {
  curPage = p;
  if (p === 'evidence') {
    loadEvidenceIntelligence();
  }
  document.querySelectorAll('.page').forEach(e => e.classList.remove('on'));
  document.querySelectorAll('.ni').forEach(e => e.classList.remove('on'));
  const targetPg = document.getElementById('page-' + p);
  const targetNi = document.getElementById('ni-' + p);
  if (targetPg) targetPg.classList.add('on');
  if (targetNi) targetNi.classList.add('on');
};

function maybePlayAlert(alertActive, isTamper) {
  if (isTamper && !_lastAlertState) {
    playAlertSound('tamper');
    _lastAlertState = true;
  } else if (alertActive && !_lastAlertState) {
    playAlertSound('alert');
    _lastAlertState = true;
  } else if (!alertActive && !isTamper) {
    _lastAlertState = false;
  }
}