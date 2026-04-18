"""
app/routes/license.py  —  v8.6.0

PROMJENE v8.6.0:
  - Dashboard: prikazuje Machine broj (hostname, OS, app verzija, IP)
  - Dashboard: statistike po tjednima, grafovi aktivnih vs. isteklih
  - Dashboard: pretraga i filtriranje po statusu, email, hostname
  - Dashboard: Admin bilješke (notes) po licenci — inline edit
  - Dashboard: Export CSV svih licenci
  - activate endpoint: prima hostname, os_platform, os_version, app_version
    i sprema ih u DB + bilježi activated_at i last_seen
  - Nova endpoint: POST /admin/license/notes/{id} — spremi admin bilješku
  - Nova endpoint: GET /admin/license/export/csv — export licenci
"""

import base64
import csv
import hashlib
import hmac
import io
import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app.auth import get_current_user, require_admin, SECRET_KEY, ALGORITHM
from app.database import SessionLocal
from app.models.license_record import LicenseRecord
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

get_current_active_user = get_current_user

_HMAC_SECRET = os.environ.get("KNJIZNICA_HMAC_SECRET", "").encode()
if not _HMAC_SECRET:
    raise RuntimeError(
        "KNJIZNICA_HMAC_SECRET env varijabla nije postavljena! "
        "Dodajte je u Render Dashboard → Environment Variables."
    )

router = APIRouter(prefix="/admin/license", tags=["License Admin"])


def _sign(payload: dict) -> str:
    p   = {k: v for k, v in sorted(payload.items()) if k != "sig"}
    msg = json.dumps(p, separators=(",", ":"), sort_keys=True).encode()
    return hmac.new(_HMAC_SECRET, msg, hashlib.sha256).hexdigest()


def _generate_key(email: str, days: int, machine_id: str = "", issued_date: str = None, expiry_date: str = None) -> str:
    issued = issued_date or date.today().isoformat()
    expiry = expiry_date or (date.today() + timedelta(days=days)).isoformat()
    payload = {"v": 2, "email": email, "issued": issued, "expiry": expiry, "mid": machine_id}
    payload["sig"] = _sign(payload)
    return base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()


def _decode_key(key: str) -> dict:
    raw = base64.b64decode(key.strip().encode()).decode()
    return json.loads(raw)


# ─────────────────────────────────────────────────────────────────────────────
# HTML nadzorna ploča — v8.6.0
# ─────────────────────────────────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="hr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>License Manager v8.6.0</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:20px;min-height:100vh}
.container{max-width:1200px;margin:0 auto}
.card{background:rgba(22,33,62,.95);padding:24px;border-radius:15px;box-shadow:0 20px 40px rgba(0,0,0,.3);margin-bottom:20px}
h1{text-align:center;color:#4cc9f0;margin-bottom:4px;font-size:1.9em}
.sub{text-align:center;color:#b0b3b8;margin-bottom:0;font-size:.88em}
.version-badge{display:inline-block;background:#4cc9f0;color:#000;font-size:.7em;font-weight:700;padding:2px 8px;border-radius:10px;margin-left:8px;vertical-align:middle}

/* Stats grid */
.stats{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:0}
.stat{background:#0f3460;padding:12px 10px;border-radius:10px;text-align:center;border-top:3px solid #4cc9f0;cursor:pointer;transition:transform .15s}
.stat:hover{transform:translateY(-2px)}
.stat.green{border-top-color:#2ecc71}
.stat.red{border-top-color:#e74c3c}
.stat.orange{border-top-color:#f39c12}
.stat.purple{border-top-color:#9b59b6}
.stat.gray{border-top-color:#666}
.snum{font-size:1.7em;font-weight:700;color:#4cc9f0}
.stat.green .snum{color:#2ecc71}
.stat.red .snum{color:#e74c3c}
.stat.orange .snum{color:#f39c12}
.stat.purple .snum{color:#9b59b6}
.stat.gray .snum{color:#999}
.slbl{font-size:.72em;color:#b0b3b8;margin-top:2px}

/* Toolbar */
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
.toolbar input{flex:1;min-width:200px;padding:9px 12px;border:2px solid #333;border-radius:7px;background:#0f3460;color:#fff;font-size:13px}
.toolbar input:focus{border-color:#4cc9f0;outline:none}
.toolbar select{padding:9px 12px;border:2px solid #333;border-radius:7px;background:#0f3460;color:#fff;font-size:13px;cursor:pointer}
.toolbar select:focus{border-color:#4cc9f0;outline:none}

/* Buttons */
.btn{padding:9px 16px;border:none;border-radius:7px;font-size:12px;font-weight:700;cursor:pointer;transition:all .2s;white-space:nowrap}
.btn-primary{background:linear-gradient(45deg,#4cc9f0,#6a11cb);color:#fff}
.btn-primary:hover{transform:translateY(-1px);box-shadow:0 6px 16px rgba(76,201,240,.35)}
.btn-green{background:#1a6b40;color:#fff}
.btn-green:hover{background:#0f5030}
.btn-export{background:#27ae60;color:#fff}
.btn-export:hover{background:#1e8449}
.btn-refresh{background:#2980b9;color:#fff}
.btn-refresh:hover{background:#1a6391}
.btn-sm{padding:3px 10px;font-size:11px;width:auto;border-radius:5px;border:none;cursor:pointer;font-weight:600}
.btn-danger{background:#c0392b;color:#fff}
.btn-danger:hover{background:#e74c3c}
.btn-warn{background:#e67e22;color:#fff}
.btn-warn:hover{background:#f39c12}
.btn-muted{background:#444;color:#ccc}
.btn-muted:hover{background:#555}
.btn-note{background:#2c3e50;color:#9b59b6;border:1px solid #9b59b6}
.btn-note:hover{background:#9b59b6;color:#fff}

/* Generate form */
.gen-form{display:grid;grid-template-columns:1fr 100px 150px 1fr auto;gap:10px;align-items:end}
label{display:block;margin-bottom:4px;color:#b0b3b8;font-size:.82em;font-weight:500}
input[type=email],input[type=number],input[type=text]{width:100%;padding:9px 10px;border:2px solid #333;border-radius:7px;background:#0f3460;color:#fff;font-size:13px}
input:focus{border-color:#4cc9f0;outline:none}
.result{margin-top:10px;padding:12px;border-radius:9px;font-family:monospace;font-size:12px;word-break:break-all;display:none}
.ok{background:rgba(46,204,113,.18);border:1px solid #2ecc71}
.err{background:rgba(231,76,60,.18);border:1px solid #e74c3c}

/* Table */
table{width:100%;border-collapse:collapse;font-size:12px}
th{background:#0f3460;padding:9px 10px;text-align:left;color:#4cc9f0;border-bottom:2px solid #333;white-space:nowrap}
td{padding:7px 10px;border-bottom:1px solid #1e2d4a;vertical-align:middle}
tr:hover td{background:rgba(76,201,240,.05)}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;text-transform:uppercase}
.badge-active{background:rgba(46,204,113,.22);color:#2ecc71;border:1px solid #2ecc71}
.badge-expired{background:rgba(231,76,60,.22);color:#e74c3c;border:1px solid #e74c3c}
.badge-revoked{background:rgba(160,160,160,.18);color:#aaa;border:1px solid #666}
.key-mono{font-family:monospace;font-size:10px;color:#4cc9f0;cursor:pointer;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-block;vertical-align:middle}
.key-mono:hover{text-decoration:underline}
.machine-info{font-size:10px;color:#888;line-height:1.5}
.machine-info .mid{color:#9ab8d8;font-family:monospace}
.machine-info .host{color:#e8c17a}
.machine-info .os{color:#aaa}
.actions-cell{white-space:nowrap;display:flex;gap:4px;align-items:center;flex-wrap:wrap}
#no-rec{text-align:center;padding:28px;color:#6c757d;display:none}
.note-text{font-size:10px;color:#9b59b6;font-style:italic;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.note-text:empty::before{content:'—';color:#444}

/* Modal */
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:1000;align-items:center;justify-content:center}
.modal-overlay.show{display:flex}
.modal{background:#16213e;border:1px solid #4cc9f0;border-radius:12px;padding:24px;min-width:400px;max-width:560px;width:90%}
.modal h3{color:#4cc9f0;margin-bottom:16px}
.modal textarea{width:100%;height:90px;background:#0f3460;border:2px solid #333;border-radius:7px;color:#fff;padding:10px;font-size:13px;resize:vertical}
.modal textarea:focus{border-color:#4cc9f0;outline:none}
.modal-btns{display:flex;gap:10px;justify-content:flex-end;margin-top:14px}

/* Pagination */
.pagination{display:flex;gap:6px;align-items:center;justify-content:center;margin-top:14px;flex-wrap:wrap}
.pagination button{background:#0f3460;border:1px solid #333;color:#fff;padding:5px 11px;border-radius:5px;cursor:pointer;font-size:12px}
.pagination button.active{background:#4cc9f0;color:#000;border-color:#4cc9f0}
.pagination button:hover:not(.active){border-color:#4cc9f0}
.page-info{color:#888;font-size:12px}

/* Section title */
.stitle{font-size:1em;color:#4cc9f0;border-bottom:1px solid #1e2d4a;padding-bottom:6px;margin-bottom:14px;font-weight:600}
.tip{font-size:11px;color:#556;margin-top:4px}

/* Expiry warning */
.expiry-soon{color:#f39c12}
.expiry-ok{color:#2ecc71}
.expiry-expired{color:#e74c3c}
</style>
</head>
<body>
<div class="container">

<!-- Header -->
<div class="card" style="margin-bottom:16px;padding:18px 24px">
  <h1>🔑 License Manager <span class="version-badge">v8.6.0</span></h1>
  <p class="sub">Knjižnica — Upravljanje licencama korisnika</p>
</div>

<!-- Stats -->
<div class="card" style="padding:18px 24px">
  <div class="stats">
    <div class="stat" onclick="filterByStatus('')">
      <div class="snum" id="s-total">–</div><div class="slbl">Ukupno</div>
    </div>
    <div class="stat green" onclick="filterByStatus('active')">
      <div class="snum" id="s-active">–</div><div class="slbl">Aktivnih</div>
    </div>
    <div class="stat red" onclick="filterByStatus('expired')">
      <div class="snum" id="s-expired">–</div><div class="slbl">Isteklih</div>
    </div>
    <div class="stat gray" onclick="filterByStatus('revoked')">
      <div class="snum" id="s-revoked">–</div><div class="slbl">Opozvanih</div>
    </div>
    <div class="stat orange" onclick="filterByStatus('expiring')">
      <div class="snum" id="s-expiring">–</div><div class="slbl">Ističe ≤30d</div>
    </div>
    <div class="stat purple" onclick="filterByStatus('trial')">
      <div class="snum" id="s-trial">–</div><div class="slbl">Trial</div>
    </div>
  </div>
</div>

<!-- Generate form -->
<div class="card">
  <p class="stitle">🚀 Generiraj novi ključ</p>
  <div class="gen-form">
    <div><label>Email korisnika</label><input type="email" id="email" placeholder="korisnik@example.com"></div>
    <div><label>Dana</label><input type="number" id="days" value="365" min="1" max="9999"></div>
    <div><label>&nbsp;</label><button class="btn btn-primary" onclick="generateKey()">🔑 Generiraj</button></div>
    <div>
      <label>Machine ID <span style="color:#556;font-size:10px">(prazno = floating)</span></label>
      <input type="text" id="mid" placeholder="Ostavite prazno za floating licencu">
      <p class="tip">Kupac vam šalje svoj Machine ID iz aplikacije → Postavke → Licenca → Kopiraj Machine ID</p>
    </div>
    <div style="display:flex;align-items:flex-end">
      <button class="btn btn-muted" onclick="lookupMid()">🔍 Traži MID</button>
    </div>
  </div>
  <div id="gen-result" class="result"></div>
</div>

<!-- License table -->
<div class="card">
  <p class="stitle">📋 Sve licence</p>
  <div class="toolbar">
    <input type="text" id="search" placeholder="Pretraži email, hostname, machine ID, OS, status…" oninput="applyFilters()">
    <select id="status-filter" onchange="applyFilters()">
      <option value="">Svi statusi</option>
      <option value="active">Aktivne</option>
      <option value="expired">Istekle</option>
      <option value="revoked">Opozvane</option>
      <option value="expiring">Ističe ≤30d</option>
      <option value="trial">Trial</option>
    </select>
    <button class="btn btn-refresh" onclick="loadLicenses()">🔄 Osvježi</button>
    <button class="btn btn-export" onclick="exportCsv()">⬇ CSV</button>
  </div>

  <table id="tbl">
    <thead><tr>
      <th>#</th>
      <th>Email</th>
      <th>Ključ</th>
      <th>Izdano</th>
      <th>Istječe</th>
      <th>Status</th>
      <th>Računalo (Machine info)</th>
      <th>Zadnji kontakt</th>
      <th>Bilješka</th>
      <th>Akcije</th>
    </tr></thead>
    <tbody id="tbody"></tbody>
  </table>
  <p id="no-rec">Nema zapisa.</p>
  <div class="pagination" id="pagination"></div>
</div>

</div><!-- /container -->

<!-- Notes modal -->
<div class="modal-overlay" id="notes-modal">
  <div class="modal">
    <h3>✏️ Admin bilješka</h3>
    <p style="color:#888;font-size:12px;margin-bottom:10px" id="notes-email-label"></p>
    <textarea id="notes-text" placeholder="Npr: Plaćeno 2026-04-18, kontakt: hr@example.com"></textarea>
    <div class="modal-btns">
      <button class="btn btn-muted" onclick="closeNotes()">Odustani</button>
      <button class="btn btn-primary" onclick="saveNotes()">💾 Spremi</button>
    </div>
  </div>
</div>

<script>
let allRecords = [];
let filtered = [];
let page = 1;
const PAGE_SIZE = 20;
let notesRecordId = null;

const urlParams = new URLSearchParams(window.location.search);
const token = urlParams.get('token');

async function apiFetch(url, options={}) {
  options.headers = options.headers || {};
  if (token) options.headers['Authorization'] = `Bearer ${token}`;
  return fetch(url, options);
}

// ── Init ────────────────────────────────────────────────────────────────────
loadLicenses();

// ── Load ────────────────────────────────────────────────────────────────────
async function loadLicenses() {
  const r = await apiFetch('/admin/license/list');
  const d = await r.json();
  allRecords = d.records || [];

  // Stats
  const now = new Date();
  const in30 = new Date(now.getTime() + 30*24*60*60*1000);
  let sActive=0, sExpired=0, sRevoked=0, sExpiring=0, sTrial=0;
  for (const rec of allRecords) {
    if (rec.status === 'active') sActive++;
    if (rec.status === 'expired') sExpired++;
    if (rec.status === 'revoked') sRevoked++;
    if (rec.status === 'active' && rec.days_remaining <= 30 && rec.days_remaining > 0) sExpiring++;
    if ((rec.created_by||'').includes('trial')) sTrial++;
  }
  document.getElementById('s-total').textContent   = allRecords.length;
  document.getElementById('s-active').textContent  = sActive;
  document.getElementById('s-expired').textContent = sExpired;
  document.getElementById('s-revoked').textContent = sRevoked;
  document.getElementById('s-expiring').textContent = sExpiring;
  document.getElementById('s-trial').textContent   = sTrial;

  applyFilters();
}

function applyFilters() {
  const q = document.getElementById('search').value.toLowerCase().trim();
  const sf = document.getElementById('status-filter').value;

  filtered = allRecords.filter(r => {
    // Status filter
    if (sf === 'expiring') {
      if (!(r.status === 'active' && r.days_remaining > 0 && r.days_remaining <= 30)) return false;
    } else if (sf === 'trial') {
      if (!(r.created_by||'').includes('trial')) return false;
    } else if (sf && r.status !== sf) {
      return false;
    }
    // Search
    if (!q) return true;
    const fields = [r.email, r.status, r.machine_id||'', r.hostname||'', r.os_platform||'', r.os_version||'', r.created_by||'', r.notes||''];
    return fields.some(f => f.toLowerCase().includes(q));
  });
  page = 1;
  renderTable();
}

function filterByStatus(status) {
  document.getElementById('status-filter').value = status;
  applyFilters();
}

// ── Render ───────────────────────────────────────────────────────────────────
function renderTable() {
  const tb = document.getElementById('tbody');
  const nr = document.getElementById('no-rec');
  if (!filtered.length) { tb.innerHTML=''; nr.style.display='block'; renderPagination(); return; }
  nr.style.display = 'none';

  const start = (page-1)*PAGE_SIZE;
  const pageRecs = filtered.slice(start, start+PAGE_SIZE);

  tb.innerHTML = pageRecs.map(r => {
    // Expiry styling
    let expClass = '';
    if (r.status === 'expired') expClass = 'expiry-expired';
    else if (r.days_remaining > 0 && r.days_remaining <= 30) expClass = 'expiry-soon';
    else expClass = 'expiry-ok';

    const daysLabel = r.days_remaining > 0 ? `<br><small class="${expClass}">još ${r.days_remaining}d</small>` : '';

    // Machine info block
    const midShort = r.machine_id ? r.machine_id.substring(0,16)+'…' : 'floating';
    const midTitle = r.machine_id || '';
    const hostLine  = r.hostname   ? `<div class="host">🖥 ${escHtml(r.hostname)}</div>` : '';
    const osLine    = (r.os_platform||r.os_version) 
      ? `<div class="os">${escHtml((r.os_platform||'')+' '+(r.os_version||''))} ${r.app_version?'· v'+escHtml(r.app_version):''}</div>` : '';
    const actCount  = r.activation_count > 0 ? `<div style="color:#556">Aktivacija: ${r.activation_count}×</div>` : '';
    const machineBlock = `<div class="machine-info">
      <div class="mid" title="${midTitle}" onclick="copyText('${midTitle}')" style="cursor:pointer">MID: ${midShort}</div>
      ${hostLine}${osLine}${actCount}
    </div>`;

    // Last seen
    const lastSeen = r.last_seen ? `<span style="color:#888;font-size:11px">${r.last_seen}</span>` : '<span style="color:#444">—</span>';

    // Note
    const noteHtml = `<span class="note-text" title="${escHtml(r.notes||'')}">` + escHtml(r.notes||'') + `</span>`;

    // Actions
    const revokeBtn = r.is_active
      ? `<button class="btn-sm btn-danger" onclick="revoke(${r.id})">Opozovi</button>` 
      : '<span style="color:#555;font-size:10px">—</span>';

    return `<tr id="row-${r.id}">
      <td>${r.id}</td>
      <td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(r.email)}">${escHtml(r.email)}</td>
      <td><span class="key-mono" title="${r.license_key}" onclick="copyText('${r.license_key}')">${r.license_key.substring(0,28)}…</span></td>
      <td style="white-space:nowrap">${r.issued||'–'}</td>
      <td style="white-space:nowrap">${r.expiry||'–'}${daysLabel}</td>
      <td><span class="badge badge-${r.status}">${r.status}</span>${(r.created_by||'').includes('trial')?'<br><span style="color:#9b59b6;font-size:9px">TRIAL</span>':''}</td>
      <td>${machineBlock}</td>
      <td>${lastSeen}</td>
      <td>${noteHtml}</td>
      <td><div class="actions-cell">
        ${revokeBtn}
        <button class="btn-sm btn-warn" onclick="resetMid(${r.id})" title="Reset Machine ID — za promjenu računala">🔄</button>
        <button class="btn-sm btn-note" onclick="openNotes(${r.id},'${escHtml(r.email)}','${escHtml(r.notes||'')}')" title="Uredi bilješku">✏️</button>
        <button class="btn-sm btn-muted" onclick="deleteRec(${r.id})" title="Trajno obriši">🗑</button>
      </div></td>
    </tr>`;
  }).join('');

  renderPagination();
}

function renderPagination() {
  const total = filtered.length;
  const pages = Math.ceil(total / PAGE_SIZE);
  const pg = document.getElementById('pagination');
  if (pages <= 1) { pg.innerHTML=''; return; }

  let html = `<span class="page-info">${total} zapisa</span>`;
  for (let i=1; i<=pages; i++) {
    html += `<button class="${i===page?'active':''}" onclick="goPage(${i})">${i}</button>`;
  }
  pg.innerHTML = html;
}

function goPage(p) { page=p; renderTable(); }

// ── Generate ─────────────────────────────────────────────────────────────────
async function generateKey(){
  const email = document.getElementById('email').value.trim();
  const days  = parseInt(document.getElementById('days').value)||365;
  const mid   = document.getElementById('mid').value.trim();
  if(!email){show('gen-result','⚠️ Unesite email!','err');return;}
  const btn=event.target; btn.textContent='Generiram...'; btn.disabled=true;
  try{
    const fd=new FormData(); fd.append('email',email); fd.append('days',days); fd.append('machine_id',mid);
    const r=await apiFetch('/admin/license/generate',{method:'POST',body:fd});
    const d=await r.json();
    if(r.ok){
      show('gen-result',
        `✅ Ključ generiran za <strong>${escHtml(d.email)}</strong> (${d.days} dana${d.machine_id?' · vezano uz računalo':' · floating'}):<br>
         <span class="key-mono" style="max-width:100%;display:block;white-space:normal" onclick="copyText('${d.key}')">${d.key}</span>
         <br><small style="color:#aaa">Kliknite na ključ za kopiranje.</small>`, 'ok');
      loadLicenses();
    }else{ show('gen-result','❌ '+((d.detail)||r.statusText),'err'); }
  }catch(e){show('gen-result','❌ '+e.message,'err');}
  finally{btn.textContent='🔑 Generiraj';btn.disabled=false;}
}

async function lookupMid(){
  const email=document.getElementById('email').value.trim();
  if(!email){alert('Unesite email za pretraživanje.');return;}
  const found=allRecords.find(x=>x.email===email&&x.machine_id);
  if(found){document.getElementById('mid').value=found.machine_id;alert('Machine ID pronađen i uneseden.');}
  else{alert('Nema Machine ID za taj email.');}
}

// ── Actions ──────────────────────────────────────────────────────────────────
async function revoke(id){
  if(!confirm('Opozovati ovu licencu?'))return;
  const r=await apiFetch(`/admin/license/revoke/${id}`,{method:'POST'});
  r.ok?loadLicenses():alert('Greška: '+(await r.json().catch(()=>({}))).detail);
}

async function resetMid(id){
  if(!confirm('Resetirati Machine ID?\\n\\nOvo omogućuje korisniku aktivaciju na drugom računalu.'))return;
  const r=await apiFetch(`/admin/license/reset-mid/${id}`,{method:'POST'});
  r.ok?loadLicenses():alert('Greška pri resetiranju.');
}

async function deleteRec(id){
  if(!confirm('Trajno obrisati zapis licence?'))return;
  const r=await apiFetch(`/admin/license/${id}`,{method:'DELETE'});
  r.ok?loadLicenses():alert('Greška pri brisanju.');
}

// ── Notes modal ───────────────────────────────────────────────────────────────
function openNotes(id, email, currentNote) {
  notesRecordId = id;
  document.getElementById('notes-email-label').textContent = email;
  document.getElementById('notes-text').value = currentNote || '';
  document.getElementById('notes-modal').classList.add('show');
}

function closeNotes() {
  document.getElementById('notes-modal').classList.remove('show');
  notesRecordId = null;
}

async function saveNotes() {
  if (!notesRecordId) return;
  const notes = document.getElementById('notes-text').value;
  const fd = new FormData();
  fd.append('notes', notes);
  const r = await apiFetch(`/admin/license/notes/${notesRecordId}`, {method:'POST', body:fd});
  if (r.ok) { closeNotes(); loadLicenses(); }
  else alert('Greška pri spremanju bilješke.');
}

// ── Export CSV ───────────────────────────────────────────────────────────────
async function exportCsv(){
  const url = '/admin/license/export/csv' + (token ? `?token=${token}` : '');
  window.open(url, '_blank');
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function copyText(txt){
  navigator.clipboard.writeText(txt).then(()=>{
    const n=document.createElement('div');
    n.textContent='✅ Kopirano!';
    n.style.cssText='position:fixed;top:20px;right:20px;background:#2ecc71;color:#000;padding:8px 16px;border-radius:8px;font-weight:700;z-index:9999;font-size:13px';
    document.body.appendChild(n);
    setTimeout(()=>n.remove(),1800);
  });
}

function escHtml(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

function show(id,html,cls){
  const el=document.getElementById(id);
  el.className='result '+cls; el.style.display='block'; el.innerHTML=html;
  el.scrollIntoView({behavior:'smooth'});
}

// Click outside modal closes it
document.getElementById('notes-modal').addEventListener('click', function(e){
  if(e.target===this) closeNotes();
});
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
async def license_dashboard(request: Request, token: Optional[str] = Query(None)):
    from jose import jwt, JWTError
    from app.models.user import UserRole

    auth_token = token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        auth_token = auth_header.split(" ", 1)[1]

    if not auth_token:
        raise HTTPException(status_code=401, detail="Token nedostaje. Prijavite se.")

    try:
        payload = jwt.decode(auth_token, SECRET_KEY, algorithms=[ALGORITHM])
        role = payload.get("role")
        if role != UserRole.admin:
            raise HTTPException(status_code=403, detail="Samo admin može pristupiti dashboardu.")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token neispravan ili istekao.")

    return DASHBOARD_HTML


@router.post("/generate")
async def generate_key(
    email:      str = Form(...),
    days:       int = Form(365),
    machine_id: str = Form(""),
    current_user=Depends(require_admin),
):
    key    = _generate_key(email, int(days), machine_id.strip())
    expiry = datetime.now(timezone.utc) + timedelta(days=int(days))

    db = SessionLocal()
    try:
        existing = db.query(LicenseRecord).filter(
            LicenseRecord.email == email,
            LicenseRecord.is_active == True
        ).first()
        if existing and not machine_id:
            raise HTTPException(status_code=400, detail="Aktivna licenca već postoji za ovaj email.")

        record = LicenseRecord(
            email       = email,
            license_key = key,
            issued      = datetime.now(timezone.utc),
            expiry      = expiry,
            machine_id  = machine_id.strip() or None,
            created_by  = current_user.username,
            is_active   = True,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Greška pri spremanju u bazu.")
    finally:
        db.close()

    return {
        "key":        key,
        "email":      email,
        "days":       days,
        "machine_id": machine_id.strip(),
        "expiry":     expiry.strftime("%Y-%m-%d"),
        "record_id":  record.id,
    }


@router.get("/list")
async def list_licenses(current_user=Depends(require_admin)):
    db = SessionLocal()
    try:
        records = db.query(LicenseRecord).order_by(LicenseRecord.id.desc()).all()
        data    = [r.to_dict() for r in records]
        stats   = {
            "total":   len(data),
            "active":  sum(1 for r in data if r["status"] == "active"),
            "expired": sum(1 for r in data if r["status"] == "expired"),
            "revoked": sum(1 for r in data if r["status"] == "revoked"),
        }
        return {"records": data, "stats": stats}
    finally:
        db.close()


@router.post("/revoke/{record_id}")
async def revoke_license(record_id: int, current_user=Depends(require_admin)):
    db = SessionLocal()
    try:
        record = db.query(LicenseRecord).filter(LicenseRecord.id == record_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="Licenca nije pronađena.")
        if not record.is_active:
            raise HTTPException(status_code=400, detail="Licenca je već opozvana.")
        record.is_active = False
        db.commit()
        return {"ok": True, "id": record_id, "email": record.email}
    finally:
        db.close()


@router.post("/activate")
async def activate_online(
    license_key: str  = Form(...),
    machine_id:  str  = Form(...),
    hostname:    str  = Form(""),
    os_platform: str  = Form(""),
    os_version:  str  = Form(""),
    app_version: str  = Form(""),
):
    """
    Online aktivacija — poziva desktop .exe pri pokretanju.
    v8.6.0: prima i sprema hostname, OS info, app verziju.
    """
    if not machine_id or len(machine_id) < 5:
        raise HTTPException(status_code=400, detail="Machine ID je obavezan i mora biti validan.")

    key = license_key.strip()

    try:
        raw     = base64.b64decode(key.encode()).decode()
        payload = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Neispravan format ključa.")

    for field in ("email", "expiry", "sig"):
        if field not in payload:
            raise HTTPException(status_code=400, detail=f"Ključ ne sadrži polje '{field}'.")

    p   = {k: v for k, v in sorted(payload.items()) if k != "sig"}
    msg = json.dumps(p, separators=(",", ":"), sort_keys=True).encode()
    expected = hmac.new(_HMAC_SECRET, msg, hashlib.sha256).hexdigest()
    try:
        sig_match = hmac.compare_digest(
            expected.encode("ascii"),
            str(payload.get("sig", "")).encode("ascii", errors="replace"),
        )
    except Exception:
        sig_match = False
    if not sig_match:
        raise HTTPException(status_code=403, detail="Neispravan potpis ključa.")

    try:
        expiry = date.fromisoformat(payload["expiry"])
    except ValueError:
        raise HTTPException(status_code=400, detail="Neispravan datum isteka.")
    if expiry < date.today():
        raise HTTPException(status_code=403, detail=f"Licenca je istekla ({payload['expiry']}).")

    now_utc = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        record = db.query(LicenseRecord).filter(LicenseRecord.license_key == key).first()

        if record:
            if not record.is_active:
                raise HTTPException(status_code=403, detail="Licenca je opozvana.")
            if record.machine_id and machine_id and record.machine_id != machine_id:
                raise HTTPException(status_code=403, detail="Ključ je već aktiviran na drugom računalu.")
            if machine_id and not record.machine_id:
                record.machine_id    = machine_id
                record.activated_at  = now_utc
            # Update machine info on every connect
            if hostname:    record.hostname    = hostname[:255]
            if os_platform: record.os_platform = os_platform[:64]
            if os_version:  record.os_version  = os_version[:128]
            if app_version: record.app_version = app_version[:32]
            record.last_seen         = now_utc
            record.activation_count  = (record.activation_count or 0) + 1
            db.commit()
        else:
            try:
                new_record = LicenseRecord(
                    email            = payload["email"],
                    license_key      = key,
                    issued           = now_utc,
                    expiry           = datetime.combine(expiry, datetime.min.time()),
                    machine_id       = machine_id.strip() or None,
                    hostname         = hostname[:255] if hostname else None,
                    os_platform      = os_platform[:64] if os_platform else None,
                    os_version       = os_version[:128] if os_version else None,
                    app_version      = app_version[:32] if app_version else None,
                    activated_at     = now_utc,
                    last_seen        = now_utc,
                    activation_count = 1,
                    created_by       = "offline_activation",
                    is_active        = True,
                )
                db.add(new_record)
                db.commit()
            except Exception:
                db.rollback()

        bound_key = _generate_key(
            email=payload["email"],
            days=0,
            machine_id=machine_id,
            issued_date=payload.get("issued"),
            expiry_date=payload.get("expiry")
        )

        return {
            "ok":          True,
            "license_key": bound_key,
            "email":       payload["email"],
            "expiry":      payload["expiry"]
        }
    finally:
        db.close()


@router.get("/status")
async def get_license_status(current_user=Depends(get_current_active_user)):
    return {"message": "Koristite lokalnu provjeru licence u desktop aplikaciji.", "server": "ok"}


@router.post("/reset-mid/{record_id}")
async def reset_machine_id(record_id: int, current_user=Depends(require_admin)):
    db = SessionLocal()
    try:
        record = db.query(LicenseRecord).filter(LicenseRecord.id == record_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="Licenca nije pronađena.")
        old_mid = record.machine_id
        record.machine_id   = None
        record.hostname     = None
        record.os_platform  = None
        record.os_version   = None
        record.activated_at = None
        db.commit()
        return {"ok": True, "id": record_id, "email": record.email, "old_mid": old_mid,
                "message": "Machine ID resetiran. Korisnik može aktivirati ključ na novom računalu."}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Greška pri resetiranju: {str(e)}")
    finally:
        db.close()


@router.delete("/{record_id}")
async def delete_license(record_id: int, current_user=Depends(require_admin)):
    db = SessionLocal()
    try:
        record = db.query(LicenseRecord).filter(LicenseRecord.id == record_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="Licenca nije pronađena.")
        email = record.email
        db.delete(record)
        db.commit()
        return {"ok": True, "id": record_id, "email": email, "message": "Zapis trajno obrisan."}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Greška pri brisanju: {str(e)}")
    finally:
        db.close()


@router.post("/trial/init")
async def init_trial(machine_id: str = Form(...)):
    if not machine_id or len(machine_id) < 5:
        raise HTTPException(status_code=400, detail="Neispravan Machine ID.")

    db = SessionLocal()
    try:
        existing = db.query(LicenseRecord).filter(
            LicenseRecord.machine_id == machine_id,
            LicenseRecord.created_by == "system_trial"
        ).first()

        if existing:
            return {
                "ok":          True,
                "license_key": existing.license_key,
                "expiry":      existing.expiry.strftime("%Y-%m-%d"),
                "message":     "Trial je već aktiviran za ovaj uređaj."
            }

        trial_email    = f"trial-{machine_id[:8]}@system"
        expiry_date_str = (date.today() + timedelta(days=30)).isoformat()
        trial_key = _generate_key(trial_email, 30, machine_id, expiry_date=expiry_date_str)

        record = LicenseRecord(
            email       = trial_email,
            license_key = trial_key,
            issued      = datetime.now(timezone.utc),
            expiry      = datetime.combine(date.fromisoformat(expiry_date_str), datetime.min.time()),
            machine_id  = machine_id,
            activated_at = datetime.now(timezone.utc),
            last_seen    = datetime.now(timezone.utc),
            activation_count = 1,
            created_by  = "system_trial",
            is_active   = True
        )
        db.add(record)
        db.commit()
        return {"ok": True, "license_key": trial_key, "expiry": expiry_date_str}
    finally:
        db.close()


@router.post("/notes/{record_id}")
async def save_notes(record_id: int, notes: str = Form(""), current_user=Depends(require_admin)):
    """Spremi admin bilješku za licencu."""
    db = SessionLocal()
    try:
        record = db.query(LicenseRecord).filter(LicenseRecord.id == record_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="Licenca nije pronađena.")
        record.notes = notes.strip() or None
        db.commit()
        return {"ok": True, "id": record_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Greška: {str(e)}")
    finally:
        db.close()


@router.get("/export/csv")
async def export_licenses_csv(request: Request, token: Optional[str] = Query(None)):
    """Export svih licenci kao CSV datoteka."""
    from jose import jwt, JWTError
    from app.models.user import UserRole

    auth_token = token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        auth_token = auth_header.split(" ", 1)[1]
    if not auth_token:
        raise HTTPException(status_code=401, detail="Token nedostaje.")

    try:
        p = jwt.decode(auth_token, SECRET_KEY, algorithms=[ALGORITHM])
        if p.get("role") != UserRole.admin:
            raise HTTPException(status_code=403, detail="Samo admin.")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token neispravan.")

    db = SessionLocal()
    try:
        records = db.query(LicenseRecord).order_by(LicenseRecord.id).all()
        output  = io.StringIO()
        writer  = csv.writer(output)
        writer.writerow(["ID","Email","Status","Izdano","Istječe","DanaPreostalo",
                         "MachineID","Hostname","OS","AppVerz","Aktivacija","ZadnjiKontakt",
                         "BrojAkt","Kreirao","Bilješka"])
        for r in records:
            d = r.to_dict()
            writer.writerow([d["id"],d["email"],d["status"],d["issued"],d["expiry"],
                             d["days_remaining"],d["machine_id"]or"",d["hostname"]or"",
                             f"{d['os_platform']or''} {d['os_version']or''}".strip(),
                             d["app_version"]or"",d["activated_at"]or"",d["last_seen"]or"",
                             d["activation_count"],d["created_by"]or"",d["notes"]or""])
        output.seek(0)
        fname = f"licence_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={fname}"}
        )
    finally:
        db.close()
