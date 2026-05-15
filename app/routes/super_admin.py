"""
app/routes/super_admin.py — SUPER ADMIN PANEL v1.0.0

Kompletni nadzorni panel za globalnog super-administratora.
Pristup: samo korisnici s role=admin i library_id=NULL (globalni admin).

Uključuje:
  - Pregled globalnih statistika
  - Upravljanje knjižnicama (CRUD + aktivacija)
  - Upravljanje korisnicima (svi korisnici svih knjižnica)
  - License Manager (iz /admin/license/)

Rute:
  GET  /admin/super/dashboard         — HTML panel
  GET  /admin/super/stats             — globalne statistike
  GET  /admin/super/libraries-stats   — knjižnice s statistikama
  POST /admin/super/libraries         — nova knjižnica
  PUT  /admin/super/libraries/{id}    — uredi knjižnicu
  POST /admin/super/libraries/{id}/toggle — aktiv./deaktiv.
  GET  /admin/super/users             — svi korisnici
  POST /admin/super/users             — novi korisnik
  PUT  /admin/super/users/{id}        — uredi korisnika
  DELETE /admin/super/users/{id}      — obriši korisnika
"""

from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from app.auth import get_current_user, SECRET_KEY, ALGORITHM, hash_password
from app.password_crypto import encrypt_password, decrypt_password
from app.database import SessionLocal
from app.models.library import Library
from app.models.user import User, UserRole
from app.models.license_record import LicenseRecord
from app.models.models import Book, Member, Loan

router = APIRouter(prefix="/admin/super", tags=["Super Admin"])


# ─── Auth helper ─────────────────────────────────────────────────────────────

def require_super_admin(request: Request, token: Optional[str] = Query(None)):
    """Provjera: mora biti admin BEZ library_id (globalni super-admin)."""
    from jose import jwt, JWTError

    auth_token = token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        auth_token = auth_header.split(" ", 1)[1]
    if not auth_token:
        raise HTTPException(status_code=401, detail="Token nedostaje.")
    try:
        payload = jwt.decode(auth_token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Token neispravan ili istekao.")

    role = payload.get("role")
    library_id = payload.get("library_id")

    if role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Samo admin može pristupiti Super Admin panelu.")
    if library_id is not None:
        raise HTTPException(status_code=403, detail="Samo GLOBALNI admin (bez library_id) ima pristup.")
    return payload


def _get_token_from_request(request: Request, token: Optional[str] = None) -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1]
    return token or ""


# ─── HTML Dashboard ────────────────────────────────────────────────────────────

SUPER_ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="hr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Super Admin Panel — Knjižnica v9.0</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
/* ── Reset & Base ── */
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#060b14;
  --bg2:#0a1220;
  --bg3:#0f1b2d;
  --surface:#111d31;
  --surface2:#162540;
  --border:#1e3050;
  --border2:#254070;
  --accent:#00c8ff;
  --accent2:#0090cc;
  --accent3:#00ff9d;
  --accent4:#ff6b35;
  --accent5:#b76fff;
  --text:#e8f4ff;
  --text2:#8aa8c8;
  --text3:#4a6a8a;
  --danger:#ff4757;
  --warning:#ffa502;
  --success:#2ed573;
  --radius:10px;
  --sidebar:240px;
  --font:'Space Grotesk',sans-serif;
  --mono:'JetBrains Mono',monospace;
}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:var(--font);font-size:14px;line-height:1.5}

/* ── Layout ── */
.app{display:flex;height:100vh;overflow:hidden}

/* ── Sidebar ── */
.sidebar{
  width:var(--sidebar);
  background:var(--bg2);
  border-right:1px solid var(--border);
  display:flex;flex-direction:column;
  flex-shrink:0;
  position:relative;
  overflow:hidden;
}
.sidebar::before{
  content:'';position:absolute;top:0;left:0;right:0;height:200px;
  background:radial-gradient(ellipse at 50% 0%,rgba(0,200,255,.12) 0%,transparent 70%);
  pointer-events:none;
}
.sidebar-logo{
  padding:20px 20px 16px;
  border-bottom:1px solid var(--border);
}
.logo-mark{
  display:flex;align-items:center;gap:10px;margin-bottom:4px;
}
.logo-icon{
  width:34px;height:34px;
  background:linear-gradient(135deg,var(--accent),var(--accent5));
  border-radius:9px;
  display:flex;align-items:center;justify-content:center;
  font-size:16px;flex-shrink:0;
  box-shadow:0 0 16px rgba(0,200,255,.3);
}
.logo-text{font-size:14px;font-weight:700;color:var(--text);letter-spacing:-.3px}
.logo-sub{font-size:10px;color:var(--accent);font-weight:600;letter-spacing:2px;text-transform:uppercase}
.version-tag{
  display:inline-flex;align-items:center;gap:4px;
  background:rgba(0,200,255,.1);border:1px solid rgba(0,200,255,.2);
  color:var(--accent);font-size:9px;font-weight:700;
  padding:2px 7px;border-radius:20px;letter-spacing:.5px;margin-top:6px;
}
.version-tag::before{content:'';width:5px;height:5px;border-radius:50%;background:var(--accent3);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

.nav{flex:1;padding:12px 10px;overflow-y:auto}
.nav-section{font-size:9px;font-weight:700;color:var(--text3);letter-spacing:2px;text-transform:uppercase;padding:8px 10px 4px}
.nav-item{
  display:flex;align-items:center;gap:10px;
  padding:9px 12px;border-radius:8px;cursor:pointer;
  font-size:13px;font-weight:500;color:var(--text2);
  transition:all .18s;margin-bottom:2px;position:relative;
}
.nav-item:hover{background:rgba(0,200,255,.07);color:var(--text)}
.nav-item.active{background:rgba(0,200,255,.12);color:var(--accent)}
.nav-item.active::before{
  content:'';position:absolute;left:0;top:20%;bottom:20%;
  width:3px;border-radius:0 3px 3px 0;background:var(--accent);
}
.nav-icon{font-size:16px;width:20px;text-align:center}
.nav-badge{
  margin-left:auto;background:var(--accent);color:#000;
  font-size:9px;font-weight:700;padding:1px 6px;border-radius:10px;
}
.nav-badge.red{background:var(--danger);color:#fff}
.nav-badge.orange{background:var(--warning);color:#000}

.sidebar-footer{
  padding:12px 16px;border-top:1px solid var(--border);
  display:flex;align-items:center;gap:10px;
}
.user-avatar{
  width:30px;height:30px;border-radius:8px;
  background:linear-gradient(135deg,var(--accent5),var(--accent));
  display:flex;align-items:center;justify-content:center;
  font-size:13px;font-weight:700;color:#fff;flex-shrink:0;
}
.user-name{font-size:12px;font-weight:600;color:var(--text)}
.user-role{font-size:10px;color:var(--accent);font-weight:600}
.logout-btn{
  margin-left:auto;background:none;border:none;color:var(--text3);
  cursor:pointer;font-size:16px;transition:color .2s;
}
.logout-btn:hover{color:var(--danger)}

/* ── Main ── */
.main{flex:1;overflow-y:auto;background:var(--bg)}

/* ── Top bar ── */
.topbar{
  padding:14px 28px;
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:16px;
  background:rgba(10,18,32,.8);
  backdrop-filter:blur(10px);
  position:sticky;top:0;z-index:100;
}
.topbar-title{font-size:18px;font-weight:700;color:var(--text)}
.topbar-sub{font-size:12px;color:var(--text3);margin-top:1px}
.topbar-actions{margin-left:auto;display:flex;gap:8px;align-items:center}
.topbar-time{font-family:var(--mono);font-size:11px;color:var(--text3);background:var(--bg3);padding:5px 10px;border-radius:6px;border:1px solid var(--border)}

/* ── Content sections ── */
.section{display:none;padding:24px 28px;animation:fadeIn .25s ease}
.section.active{display:block}
@keyframes fadeIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}

/* ── Stats grid ── */
.stats-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:14px;margin-bottom:24px}
.stat-card{
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:var(--radius);
  padding:16px;
  position:relative;overflow:hidden;
  transition:transform .2s,border-color .2s;cursor:default;
}
.stat-card:hover{transform:translateY(-2px);border-color:var(--border2)}
.stat-card::after{
  content:'';position:absolute;top:0;right:0;bottom:0;width:3px;
  background:var(--card-color,var(--accent));border-radius:0 var(--radius) var(--radius) 0;
}
.stat-icon{font-size:20px;margin-bottom:8px}
.stat-value{font-size:26px;font-weight:700;color:var(--text);line-height:1;margin-bottom:4px}
.stat-label{font-size:11px;color:var(--text2);font-weight:500}
.stat-sub{font-size:10px;color:var(--text3);margin-top:2px}
.stat-card.blue{--card-color:#00c8ff}
.stat-card.green{--card-color:#00ff9d}
.stat-card.orange{--card-color:#ffa502}
.stat-card.red{--card-color:#ff4757}
.stat-card.purple{--card-color:#b76fff}
.stat-card.teal{--card-color:#1dd3b0}

/* ── Section header ── */
.sec-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
.sec-title{font-size:16px;font-weight:700;color:var(--text);display:flex;align-items:center;gap:8px}
.sec-title .icon{font-size:18px}

/* ── Buttons ── */
.btn{
  padding:8px 16px;border:none;border-radius:7px;
  font-size:12px;font-weight:600;cursor:pointer;
  transition:all .18s;display:inline-flex;align-items:center;gap:6px;
  font-family:var(--font);white-space:nowrap;
}
.btn-primary{background:linear-gradient(135deg,var(--accent2),var(--accent));color:#000;box-shadow:0 0 14px rgba(0,200,255,.2)}
.btn-primary:hover{box-shadow:0 0 22px rgba(0,200,255,.4);transform:translateY(-1px)}
.btn-success{background:rgba(0,255,157,.15);border:1px solid var(--accent3);color:var(--accent3)}
.btn-success:hover{background:rgba(0,255,157,.25)}
.btn-danger{background:rgba(255,71,87,.15);border:1px solid var(--danger);color:var(--danger)}
.btn-danger:hover{background:rgba(255,71,87,.25)}
.btn-warn{background:rgba(255,165,2,.15);border:1px solid var(--warning);color:var(--warning)}
.btn-warn:hover{background:rgba(255,165,2,.25)}
.btn-ghost{background:transparent;border:1px solid var(--border2);color:var(--text2)}
.btn-ghost:hover{border-color:var(--accent);color:var(--accent)}
.btn-sm{padding:4px 10px;font-size:11px;border-radius:5px}
.btn:disabled{opacity:.4;cursor:not-allowed;transform:none!important}

/* ── Tables ── */
.table-wrap{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden}
table{width:100%;border-collapse:collapse;font-size:12px}
th{background:var(--surface2);padding:10px 14px;text-align:left;color:var(--text2);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--border)}
td{padding:10px 14px;border-bottom:1px solid var(--border);vertical-align:middle;color:var(--text)}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(0,200,255,.03)}

/* ── Badges ── */
.badge{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.3px}
.badge::before{content:'';width:5px;height:5px;border-radius:50%;flex-shrink:0}
.badge-active{background:rgba(0,255,157,.12);color:var(--accent3);border:1px solid rgba(0,255,157,.25)}
.badge-active::before{background:var(--accent3)}
.badge-inactive{background:rgba(255,71,87,.1);color:var(--danger);border:1px solid rgba(255,71,87,.2)}
.badge-inactive::before{background:var(--danger)}
.badge-admin{background:rgba(0,200,255,.12);color:var(--accent);border:1px solid rgba(0,200,255,.2)}
.badge-knjiznicar{background:rgba(183,111,255,.12);color:var(--accent5);border:1px solid rgba(183,111,255,.2)}
.badge-citac{background:rgba(139,168,200,.1);color:var(--text2);border:1px solid var(--border)}
.badge-license-active{background:rgba(0,255,157,.12);color:var(--accent3);border:1px solid rgba(0,255,157,.25)}
.badge-license-active::before{background:var(--accent3)}
.badge-license-expired{background:rgba(255,71,87,.1);color:var(--danger);border:1px solid rgba(255,71,87,.2)}
.badge-license-expired::before{background:var(--danger)}
.badge-license-revoked{background:rgba(74,106,138,.15);color:var(--text3);border:1px solid var(--border)}
.badge-license-revoked::before{background:var(--text3)}

/* ── Toolbar ── */
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.search-box{
  flex:1;min-width:200px;
  padding:8px 12px 8px 34px;
  background:var(--surface);border:1px solid var(--border);
  border-radius:7px;color:var(--text);font-size:12px;font-family:var(--font);
  position:relative;
}
.search-wrap{position:relative;flex:1;min-width:200px}
.search-wrap::before{content:'🔍';position:absolute;left:10px;top:50%;transform:translateY(-50%);font-size:13px;pointer-events:none}
.search-box:focus{outline:none;border-color:var(--accent)}
.filter-select{
  padding:8px 12px;background:var(--surface);border:1px solid var(--border);
  border-radius:7px;color:var(--text);font-size:12px;font-family:var(--font);cursor:pointer;
}
.filter-select:focus{outline:none;border-color:var(--accent)}

/* ── Modal ── */
.modal-overlay{
  display:none;position:fixed;inset:0;
  background:rgba(0,0,0,.75);backdrop-filter:blur(6px);
  z-index:1000;align-items:center;justify-content:center;
}
.modal-overlay.show{display:flex}
.modal{
  background:var(--bg3);border:1px solid var(--border2);
  border-radius:14px;padding:28px;
  min-width:420px;max-width:600px;width:90%;
  box-shadow:0 30px 80px rgba(0,0,0,.6);
  animation:modalIn .2s ease;
}
@keyframes modalIn{from{opacity:0;transform:scale(.95)}to{opacity:1;transform:scale(1)}}
.modal-title{font-size:16px;font-weight:700;color:var(--text);margin-bottom:20px;display:flex;align-items:center;gap:8px}
.modal-btns{display:flex;gap:8px;justify-content:flex-end;margin-top:20px}

/* ── Forms ── */
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.form-grid.single{grid-template-columns:1fr}
.form-group{display:flex;flex-direction:column;gap:5px}
.form-group.full{grid-column:1/-1}
label.lbl{font-size:11px;font-weight:600;color:var(--text2);text-transform:uppercase;letter-spacing:.5px}
.inp{
  padding:9px 12px;background:var(--surface2);
  border:1px solid var(--border);border-radius:7px;
  color:var(--text);font-size:13px;font-family:var(--font);
  transition:border-color .18s;
}
.inp:focus{outline:none;border-color:var(--accent)}
.inp::placeholder{color:var(--text3)}
select.inp{cursor:pointer}
textarea.inp{resize:vertical;min-height:70px}

/* ── Alerts ── */
.result-msg{
  padding:10px 14px;border-radius:7px;font-size:12px;margin-top:10px;display:none;
  animation:fadeIn .2s;
}
.result-ok{background:rgba(0,255,157,.1);border:1px solid var(--accent3);color:var(--accent3)}
.result-err{background:rgba(255,71,87,.1);border:1px solid var(--danger);color:var(--danger)}
.result-warn{background:rgba(255,165,2,.1);border:1px solid var(--warning);color:var(--warning)}

/* ── Library cards grid (alternate view) ── */
.lib-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
.lib-card{
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);padding:18px;
  transition:border-color .2s,transform .2s;
  position:relative;overflow:hidden;cursor:default;
}
.lib-card:hover{border-color:var(--border2);transform:translateY(-2px)}
.lib-card-header{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:12px}
.lib-name{font-size:15px;font-weight:700;color:var(--text)}
.lib-slug{font-family:var(--mono);font-size:10px;color:var(--text3);margin-top:2px}
.lib-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:12px;padding-top:12px;border-top:1px solid var(--border)}
.lib-stat-item{text-align:center}
.lib-stat-num{font-size:18px;font-weight:700;color:var(--accent)}
.lib-stat-lbl{font-size:9px;color:var(--text3);text-transform:uppercase;letter-spacing:.5px;margin-top:1px}
.lib-card-actions{display:flex;gap:6px;margin-top:12px}
.lib-card .corner-accent{
  position:absolute;top:0;right:0;
  width:60px;height:60px;
  background:radial-gradient(circle at 100% 0%,rgba(0,200,255,.15),transparent 70%);
  pointer-events:none;
}

/* ── License section - compact integration ── */
.license-frame{
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);overflow:hidden;
}
.license-frame-header{
  padding:12px 16px;background:var(--surface2);border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;
}
.license-frame-title{font-size:13px;font-weight:700;color:var(--text);display:flex;align-items:center;gap:6px}

/* ── License table inline ── */
.lic-stats{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:16px}
.lic-stat{
  background:var(--surface);border:1px solid var(--border);
  border-radius:8px;padding:12px 10px;text-align:center;cursor:pointer;
  transition:border-color .15s;
}
.lic-stat:hover{border-color:var(--border2)}
.lic-stat .num{font-size:22px;font-weight:700}
.lic-stat .lbl{font-size:10px;color:var(--text2);margin-top:2px}
.lic-stat.blue .num{color:var(--accent)}
.lic-stat.green .num{color:var(--accent3)}
.lic-stat.red .num{color:var(--danger)}
.lic-stat.gray .num{color:var(--text3)}
.lic-stat.orange .num{color:var(--warning)}
.lic-stat.purple .num{color:var(--accent5)}

/* Key mono style */
.key-mono{
  font-family:var(--mono);font-size:10px;color:var(--accent);
  cursor:pointer;max-width:150px;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;display:inline-block;vertical-align:middle;
}
.key-mono:hover{text-decoration:underline}
.machine-info{font-size:10px;color:var(--text2);line-height:1.6}
.machine-info .mid{color:var(--text3);font-family:var(--mono)}
.actions-cell{display:flex;gap:4px;align-items:center;flex-wrap:nowrap}

/* Expiry colors */
.expiry-ok{color:var(--accent3)}
.expiry-soon{color:var(--warning)}
.expiry-expired{color:var(--danger)}

/* ── Gen form ── */
.gen-form{display:grid;grid-template-columns:1fr 90px auto;gap:12px;align-items:end;margin-bottom:10px}

/* ── Pagination ── */
.pagination{display:flex;gap:4px;align-items:center;justify-content:flex-end;margin-top:12px;flex-wrap:wrap}
.pagination button{
  background:var(--surface);border:1px solid var(--border);
  color:var(--text2);padding:4px 10px;border-radius:5px;cursor:pointer;font-size:11px;
}
.pagination button.active{background:var(--accent);color:#000;border-color:var(--accent)}
.pagination button:hover:not(.active){border-color:var(--accent);color:var(--accent)}
.page-info{font-size:11px;color:var(--text3)}

/* ── Empty state ── */
.empty-state{text-align:center;padding:40px 20px;color:var(--text3)}
.empty-state .icon{font-size:36px;margin-bottom:10px}
.empty-state p{font-size:13px}

/* ── Loading ── */
.loading{
  display:flex;align-items:center;justify-content:center;
  padding:40px;gap:10px;color:var(--text3);font-size:13px;
}
.spinner{width:20px;height:20px;border:2px solid var(--border2);border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

/* ── Toast ── */
.toast{
  position:fixed;top:20px;right:20px;z-index:9999;
  background:var(--surface2);border:1px solid var(--border2);
  color:var(--text);padding:10px 16px;border-radius:8px;
  font-size:12px;font-weight:500;
  display:flex;align-items:center;gap:8px;
  box-shadow:0 8px 30px rgba(0,0,0,.5);
  animation:toastIn .25s ease;max-width:300px;
}
@keyframes toastIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}
.toast.ok{border-color:var(--accent3);color:var(--accent3)}
.toast.err{border-color:var(--danger);color:var(--danger)}

/* ── Divider ── */
.divider{height:1px;background:var(--border);margin:20px 0}

/* ── Notes modal textarea ── */
.note-text{font-size:10px;color:var(--accent5);font-style:italic;max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:middle;display:inline-block}

/* ── Responsive ── */
@media(max-width:768px){
  .sidebar{width:56px}
  .logo-text,.logo-sub,.nav-item span,.version-tag,.user-name,.user-role{display:none}
  .nav-icon{width:100%;text-align:center}
  .main{overflow-y:auto}
  .stats-grid{grid-template-columns:1fr 1fr}
  .form-grid{grid-template-columns:1fr}
  .gen-form{grid-template-columns:1fr}
}

/* ── Override select option dark ── */
option{background:var(--bg3);color:var(--text)}
</style>
</head>
<body>
<div class="app">

<!-- ═══ SIDEBAR ═══ -->
<aside class="sidebar">
  <div class="sidebar-logo">
    <div class="logo-mark">
      <div class="logo-icon">🏛️</div>
      <div>
        <div class="logo-text">Knjižnica</div>
        <div class="logo-sub">Super Admin</div>
      </div>
    </div>
    <div class="version-tag">v9.0.0 SUPER</div>
  </div>

  <nav class="nav">
    <div class="nav-section">Panel</div>
    <div class="nav-item active" onclick="showSection('overview')" id="nav-overview">
      <span class="nav-icon">📊</span><span>Pregled</span>
    </div>
    <div class="nav-item" onclick="showSection('libraries')" id="nav-libraries">
      <span class="nav-icon">🏛️</span><span>Knjižnice</span>
      <span class="nav-badge" id="badge-libraries">–</span>
    </div>
    <div class="nav-item" onclick="showSection('users')" id="nav-users">
      <span class="nav-icon">👥</span><span>Korisnici</span>
      <span class="nav-badge" id="badge-users">–</span>
    </div>
    <div class="nav-section">Licence</div>
    <div class="nav-item" onclick="showSection('licenses')" id="nav-licenses">
      <span class="nav-icon">🔑</span><span>License Manager</span>
      <span class="nav-badge red" id="badge-licenses">–</span>
    </div>
    <div class="nav-section">Sustav</div>
    <div class="nav-item" onclick="showSection('system')" id="nav-system">
      <span class="nav-icon">⚙️</span><span>Sustav</span>
    </div>
  </nav>

  <div class="sidebar-footer">
    <div class="user-avatar" id="avatar-initials">SA</div>
    <div>
      <div class="user-name" id="sidebar-username">Admin</div>
      <div class="user-role">Super Admin</div>
    </div>
    <button class="logout-btn" onclick="logout()" title="Odjava">⬡</button>
  </div>
</aside>

<!-- ═══ MAIN ═══ -->
<main class="main">

  <!-- Top bar -->
  <div class="topbar">
    <div>
      <div class="topbar-title" id="topbar-title">📊 Pregled sustava</div>
      <div class="topbar-sub" id="topbar-sub">Globalni nadzor svih knjižnica</div>
    </div>
    <div class="topbar-actions">
      <div class="topbar-time" id="clock">--:--:--</div>
      <button class="btn btn-ghost btn-sm" onclick="refreshAll()">🔄 Osvježi</button>
    </div>
  </div>

  <!-- ══ SECTION: OVERVIEW ══ -->
  <div class="section active" id="section-overview">
    <div class="stats-grid" id="global-stats">
      <div class="stat-card blue"><div class="stat-icon">🏛️</div><div class="stat-value" id="g-libs">–</div><div class="stat-label">Knjižnice</div><div class="stat-sub" id="g-libs-active"></div></div>
      <div class="stat-card green"><div class="stat-icon">📚</div><div class="stat-value" id="g-books">–</div><div class="stat-label">Ukupno knjiga</div></div>
      <div class="stat-card teal"><div class="stat-icon">👤</div><div class="stat-value" id="g-members">–</div><div class="stat-label">Aktivnih članova</div></div>
      <div class="stat-card orange"><div class="stat-icon">📖</div><div class="stat-value" id="g-loans">–</div><div class="stat-label">Aktivnih posudbi</div></div>
      <div class="stat-card red"><div class="stat-icon">⏰</div><div class="stat-value" id="g-overdue">–</div><div class="stat-label">Prekoračenih</div></div>
      <div class="stat-card purple"><div class="stat-icon">👥</div><div class="stat-value" id="g-users">–</div><div class="stat-label">Korisnika sustava</div></div>
      <div class="stat-card blue"><div class="stat-icon">🔑</div><div class="stat-value" id="g-lic-total">–</div><div class="stat-label">Ukupno licenci</div></div>
      <div class="stat-card green"><div class="stat-icon">✅</div><div class="stat-value" id="g-lic-active">–</div><div class="stat-label">Aktivnih licenci</div></div>
      <div class="stat-card red"><div class="stat-icon">⛔</div><div class="stat-value" id="g-lic-expired">–</div><div class="stat-label">Isteklih licenci</div></div>
    </div>

    <div class="sec-header">
      <div class="sec-title"><span class="icon">🏛️</span> Pregled knjižnica</div>
    </div>
    <div class="lib-grid" id="lib-overview-grid">
      <div class="loading"><div class="spinner"></div> Učitavam...</div>
    </div>
  </div>

  <!-- ══ SECTION: LIBRARIES ══ -->
  <div class="section" id="section-libraries">
    <div class="sec-header">
      <div class="sec-title"><span class="icon">🏛️</span> Upravljanje knjižnicama</div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-primary btn-sm" onclick="openLibModal()">＋ Nova knjižnica</button>
      </div>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>#</th><th>Naziv</th><th>Slug</th><th>Grad</th><th>Kontakt</th>
            <th>Knjiga</th><th>Članova</th><th>Posudbi</th>
            <th>Status</th><th>Akcije</th>
          </tr>
        </thead>
        <tbody id="lib-tbody">
          <tr><td colspan="10"><div class="loading"><div class="spinner"></div> Učitavam...</div></td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- ══ SECTION: USERS ══ -->
  <div class="section" id="section-users">
    <div class="sec-header">
      <div class="sec-title"><span class="icon">👥</span> Upravljanje korisnicima</div>
      <button class="btn btn-primary btn-sm" onclick="openUserModal()">＋ Novi korisnik</button>
    </div>

    <div class="toolbar">
      <div class="search-wrap">
        <input type="text" class="search-box" id="user-search" placeholder="Pretraži po username, imenu, emailu…" oninput="filterUsers()">
      </div>
      <select class="filter-select" id="user-lib-filter" onchange="filterUsers()">
        <option value="">Sve knjižnice</option>
      </select>
      <select class="filter-select" id="user-role-filter" onchange="filterUsers()">
        <option value="">Svi tipovi</option>
        <option value="admin">Admin</option>
        <option value="knjiznicar">Knjižničar</option>
        <option value="citac">Čitač</option>
      </select>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>#</th><th>Korisnik</th><th>Puno ime</th><th>Email</th><th>Rola</th><th>Knjižnica</th><th>Status</th><th>Akcije</th></tr>
        </thead>
        <tbody id="users-tbody">
          <tr><td colspan="8"><div class="loading"><div class="spinner"></div> Učitavam...</div></td></tr>
        </tbody>
      </table>
    </div>
    <div class="pagination" id="users-pagination"></div>
  </div>

  <!-- ══ SECTION: LICENSES ══ -->
  <div class="section" id="section-licenses">
    <div class="sec-header">
      <div class="sec-title"><span class="icon">🔑</span> License Manager</div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-ghost btn-sm" onclick="exportLicCsv()">⬇ CSV</button>
        <button class="btn btn-ghost btn-sm" onclick="loadLicenses()">🔄 Osvježi</button>
      </div>
    </div>

    <!-- Lic stats -->
    <div class="lic-stats">
      <div class="lic-stat blue" onclick="licFilter('')"><div class="num" id="ls-total">–</div><div class="lbl">Ukupno</div></div>
      <div class="lic-stat green" onclick="licFilter('active')"><div class="num" id="ls-active">–</div><div class="lbl">Aktivne</div></div>
      <div class="lic-stat red" onclick="licFilter('expired')"><div class="num" id="ls-expired">–</div><div class="lbl">Istekle</div></div>
      <div class="lic-stat gray" onclick="licFilter('revoked')"><div class="num" id="ls-revoked">–</div><div class="lbl">Opozvane</div></div>
      <div class="lic-stat orange" onclick="licFilter('expiring')"><div class="num" id="ls-expiring">–</div><div class="lbl">Ističe ≤30d</div></div>
      <div class="lic-stat purple" onclick="licFilter('trial')"><div class="num" id="ls-trial">–</div><div class="lbl">Trial</div></div>
    </div>

    <!-- Gen form -->
    <div class="license-frame" style="margin-bottom:16px;padding:16px">
      <p style="font-size:12px;font-weight:600;color:var(--text2);margin-bottom:12px">🚀 Generiraj novi ključ</p>
      <div class="gen-form">
        <div class="form-group">
          <label class="lbl">Email korisnika</label>
          <input type="email" class="inp" id="lic-email" placeholder="korisnik@example.com">
        </div>
        <div class="form-group">
          <label class="lbl">Dana</label>
          <input type="number" class="inp" id="lic-days" value="365" min="1" max="9999">
        </div>
        <div class="form-group" style="align-self:flex-end">
          <button class="btn btn-primary" onclick="generateLicense()">🔑 Generiraj</button>
        </div>
      </div>
      <div class="form-group" style="margin-top:8px">
        <label class="lbl">Machine ID <span style="color:var(--text3);font-size:9px;font-weight:400">(prazno = floating)</span></label>
        <input type="text" class="inp" id="lic-mid" placeholder="Prazno za floating licencu">
      </div>
      <div id="gen-result" class="result-msg"></div>
    </div>

    <!-- License table -->
    <div class="toolbar">
      <div class="search-wrap">
        <input type="text" class="search-box" id="lic-search" placeholder="Pretraži email, hostname, machine ID…" oninput="applyLicFilters()">
      </div>
      <select class="filter-select" id="lic-status-filter" onchange="applyLicFilters()">
        <option value="">Svi statusi</option>
        <option value="active">Aktivne</option>
        <option value="expired">Istekle</option>
        <option value="revoked">Opozvane</option>
        <option value="expiring">Ističe ≤30d</option>
        <option value="trial">Trial</option>
      </select>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>#</th><th>Email</th><th>Ključ</th><th>Izdano</th><th>Istječe</th><th>Status</th><th>Računalo</th><th>Zadnji kontakt</th><th>Bilješka</th><th>Akcije</th></tr>
        </thead>
        <tbody id="lic-tbody"></tbody>
      </table>
      <div id="lic-empty" style="display:none" class="empty-state"><div class="icon">🔑</div><p>Nema licenci.</p></div>
    </div>
    <div class="pagination" id="lic-pagination"></div>
  </div>

  <!-- ══ SECTION: SYSTEM ══ -->
  <div class="section" id="section-system">
    <div class="sec-header">
      <div class="sec-title"><span class="icon">⚙️</span> Info o sustavu</div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
      <div class="table-wrap" style="padding:20px">
        <p style="font-size:13px;font-weight:700;color:var(--text);margin-bottom:14px">📋 Informacije</p>
        <div id="sys-info" style="font-size:12px;line-height:2;color:var(--text2)">
          <div>Verzija API: <span style="color:var(--accent);font-family:var(--mono)">v9.0.0</span></div>
          <div>Arhitektura: <span style="color:var(--text)">Multi-tenant (Opcija A)</span></div>
          <div>Baza: <span style="color:var(--text)">SQLite / PostgreSQL</span></div>
          <div>Auth: <span style="color:var(--text)">JWT Bearer</span></div>
        </div>
      </div>
      <div class="table-wrap" style="padding:20px">
        <p style="font-size:13px;font-weight:700;color:var(--text);margin-bottom:14px">🔗 Brzi linkovi</p>
        <div style="display:flex;flex-direction:column;gap:8px">
          <a href="/docs" target="_blank" class="btn btn-ghost btn-sm" style="text-decoration:none;justify-content:center">📖 API Dokumentacija (Swagger)</a>
          <a href="/redoc" target="_blank" class="btn btn-ghost btn-sm" style="text-decoration:none;justify-content:center">📄 ReDoc</a>
          <button class="btn btn-ghost btn-sm" onclick="showSection('licenses')">🔑 License Manager</button>
          <button class="btn btn-ghost btn-sm" onclick="debugLicenses()">🔧 Dijagnostika licenci</button>
        </div>
      </div>
    </div>
    <div id="debug-result" class="result-msg" style="margin-top:16px"></div>
  </div>

</main>
</div>

<!-- ═══ MODALS ═══ -->

<!-- Library modal -->
<div class="modal-overlay" id="lib-modal">
  <div class="modal">
    <div class="modal-title" id="lib-modal-title">🏛️ Nova knjižnica</div>
    <div class="form-grid">
      <div class="form-group"><label class="lbl">Naziv *</label><input class="inp" id="lib-name" placeholder="Knjižnica Bugojno"></div>
      <div class="form-group"><label class="lbl">Slug * <span style="color:var(--text3);font-weight:400">(jedinstveni ID)</span></label><input class="inp" id="lib-slug" placeholder="bugojno"></div>
      <div class="form-group"><label class="lbl">Grad</label><input class="inp" id="lib-city" placeholder="Bugojno"></div>
      <div class="form-group"><label class="lbl">Adresa</label><input class="inp" id="lib-address" placeholder="Ul. Knjižna 1"></div>
      <div class="form-group"><label class="lbl">Email</label><input class="inp" type="email" id="lib-email" placeholder="info@knjiznica.ba"></div>
      <div class="form-group"><label class="lbl">Telefon</label><input class="inp" id="lib-phone" placeholder="+387 30 000 000"></div>
      <div class="form-group full"><label class="lbl">Napomena</label><textarea class="inp" id="lib-notes" placeholder="Interne napomene…"></textarea></div>
    </div>
    <div id="lib-modal-result" class="result-msg"></div>
    <div class="modal-btns">
      <button class="btn btn-ghost" onclick="closeLibModal()">Odustani</button>
      <button class="btn btn-primary" onclick="saveLibrary()" id="lib-save-btn">💾 Spremi</button>
    </div>
  </div>
</div>

<!-- User modal -->
<div class="modal-overlay" id="user-modal">
  <div class="modal">
    <div class="modal-title" id="user-modal-title">👤 Novi korisnik</div>
    <div class="form-grid">
      <div class="form-group"><label class="lbl">Korisničko ime *</label><input class="inp" id="u-username" placeholder="admin_grad"></div>
      <div class="form-group"><label class="lbl">Lozinka *</label><input class="inp" type="password" id="u-password" placeholder="••••••••"></div>
      <div class="form-group"><label class="lbl">Puno ime</label><input class="inp" id="u-fullname" placeholder="Ime Prezime"></div>
      <div class="form-group"><label class="lbl">Email</label><input class="inp" type="email" id="u-email" placeholder="korisnik@knjiznica.ba"></div>
      <div class="form-group"><label class="lbl">Rola</label>
        <select class="inp" id="u-role">
          <option value="admin">Admin</option>
          <option value="knjiznicar" selected>Knjižničar</option>
          <option value="citac">Čitač</option>
        </select>
      </div>
      <div class="form-group"><label class="lbl">Knjižnica</label>
        <select class="inp" id="u-library">
          <option value="">— Globalni (bez knjižnice) —</option>
        </select>
      </div>
    </div>
    <div id="user-modal-result" class="result-msg"></div>
    <div class="modal-btns">
      <button class="btn btn-ghost" onclick="closeUserModal()">Odustani</button>
      <button class="btn btn-primary" onclick="saveUser()" id="user-save-btn">💾 Spremi</button>
    </div>
  </div>
</div>

<!-- Notes modal (license) -->
<div class="modal-overlay" id="notes-modal">
  <div class="modal" style="min-width:380px">
    <div class="modal-title">✏️ Admin bilješka</div>
    <p style="font-size:11px;color:var(--text3);margin-bottom:12px" id="notes-email-lbl"></p>
    <textarea class="inp" id="notes-text" style="height:90px" placeholder="Npr: Plaćeno 2026-04-18, kontakt: hr@example.com"></textarea>
    <div class="modal-btns">
      <button class="btn btn-ghost" onclick="closeNotes()">Odustani</button>
      <button class="btn btn-primary" onclick="saveNotes()">💾 Spremi</button>
    </div>
  </div>
</div>

<script>
// ═══════════════════════════════════════════════════════════════
// State & Init
// ═══════════════════════════════════════════════════════════════
const urlParams = new URLSearchParams(window.location.search);
const TOKEN = urlParams.get('token') || '';

let libsData = [];
let usersData = [];
let usersFiltered = [];
const USERS_PAGE_SIZE = 25;
let usersPage = 1;

let licData = [];
let licFiltered = [];
const LIC_PAGE_SIZE = 20;
let licPage = 1;
let notesLicId = null;
let editingLibId = null;
let editingUserId = null;

// Clock
setInterval(() => {
  document.getElementById('clock').textContent = new Date().toLocaleTimeString('hr');
}, 1000);

// Init
document.addEventListener('DOMContentLoaded', () => {
  setUsernameFromToken();
  loadAll();
});

function setUsernameFromToken() {
  if (!TOKEN) return;
  try {
    const parts = TOKEN.split('.');
    const payload = JSON.parse(atob(parts[1]));
    const name = payload.sub || 'Admin';
    document.getElementById('sidebar-username').textContent = name;
    document.getElementById('avatar-initials').textContent = name.substring(0,2).toUpperCase();
  } catch(e) {}
}

async function apiFetch(url, opts={}) {
  opts.headers = opts.headers || {};
  if (TOKEN) opts.headers['Authorization'] = `Bearer ${TOKEN}`;
  return fetch(url, opts);
}

async function loadAll() {
  await Promise.all([loadGlobalStats(), loadLibsStats(), loadUsers(), loadLicenses()]);
}

function refreshAll() { loadAll(); toast('Podaci osvježeni!', 'ok'); }

// ═══════════════════════════════════════════════════════════════
// Navigation
// ═══════════════════════════════════════════════════════════════
const sectionTitles = {
  overview: ['📊 Pregled sustava', 'Globalni nadzor svih knjižnica'],
  libraries: ['🏛️ Knjižnice', 'Upravljanje svim knjižnicama (tenantima)'],
  users: ['👥 Korisnici', 'Svi korisnici kroz sve knjižnice'],
  licenses: ['🔑 License Manager', 'Upravljanje licencama korisnika desktop aplikacije'],
  system: ['⚙️ Sustav', 'Informacije i dijagnostika sustava'],
};

function showSection(name) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('section-' + name).classList.add('active');
  document.getElementById('nav-' + name).classList.add('active');
  const [title, sub] = sectionTitles[name] || ['Panel', ''];
  document.getElementById('topbar-title').textContent = title;
  document.getElementById('topbar-sub').textContent = sub;
}

function logout() {
  if (confirm('Odjaviti se?')) window.location.href = '/';
}

// ═══════════════════════════════════════════════════════════════
// Global Stats
// ═══════════════════════════════════════════════════════════════
async function loadGlobalStats() {
  try {
    const r = await apiFetch('/admin/super/stats');
    if (!r.ok) return;
    const d = await r.json();
    document.getElementById('g-libs').textContent = d.libraries || 0;
    document.getElementById('g-libs-active').textContent = `${d.libraries_active || 0} aktivnih`;
    document.getElementById('g-books').textContent = (d.books || 0).toLocaleString();
    document.getElementById('g-members').textContent = (d.members_active || 0).toLocaleString();
    document.getElementById('g-loans').textContent = (d.loans_active || 0).toLocaleString();
    document.getElementById('g-overdue').textContent = (d.loans_overdue || 0).toLocaleString();
    document.getElementById('g-users').textContent = (d.users || 0).toLocaleString();
    document.getElementById('g-lic-total').textContent = (d.lic_total || 0).toLocaleString();
    document.getElementById('g-lic-active').textContent = (d.lic_active || 0).toLocaleString();
    document.getElementById('g-lic-expired').textContent = (d.lic_expired || 0).toLocaleString();
  } catch(e) { console.error('Stats error:', e); }
}

// ═══════════════════════════════════════════════════════════════
// Libraries
// ═══════════════════════════════════════════════════════════════
async function loadLibsStats() {
  try {
    const r = await apiFetch('/admin/super/libraries-stats');
    if (!r.ok) return;
    libsData = await r.json();
    document.getElementById('badge-libraries').textContent = libsData.length;
    renderLibTable();
    renderLibOverview();
    populateLibFilter();
  } catch(e) { console.error('Libs error:', e); }
}

function renderLibTable() {
  const tbody = document.getElementById('lib-tbody');
  if (!libsData.length) {
    tbody.innerHTML = '<tr><td colspan="10"><div class="empty-state"><div class="icon">🏛️</div><p>Nema knjižnica.</p></div></td></tr>';
    return;
  }
  tbody.innerHTML = libsData.map(lib => `
    <tr>
      <td>${lib.id}</td>
      <td><strong>${esc(lib.name)}</strong></td>
      <td><code style="font-family:var(--mono);color:var(--text3);font-size:10px">${esc(lib.slug)}</code></td>
      <td>${esc(lib.city||'–')}</td>
      <td style="font-size:11px;color:var(--text2)">${esc(lib.email||'–')}<br>${esc(lib.phone||'')}</td>
      <td style="text-align:center;font-weight:700;color:var(--accent)">${lib.books||0}</td>
      <td style="text-align:center;font-weight:700;color:var(--accent3)">${lib.members||0}</td>
      <td style="text-align:center;font-weight:700;color:var(--warning)">${lib.loans||0}</td>
      <td><span class="badge ${lib.is_active?'badge-active':'badge-inactive'}">${lib.is_active?'Aktivna':'Neaktivna'}</span></td>
      <td>
        <div class="actions-cell">
          <button class="btn btn-ghost btn-sm" onclick="openLibModal(${lib.id})">✏️</button>
          <button class="btn btn-sm ${lib.is_active?'btn-warn':'btn-success'}" onclick="toggleLib(${lib.id},${lib.is_active})">
            ${lib.is_active?'⏸ Deaktiv.':'▶ Aktiv.'}
          </button>
        </div>
      </td>
    </tr>
  `).join('');
}

function renderLibOverview() {
  const grid = document.getElementById('lib-overview-grid');
  grid.innerHTML = libsData.map(lib => `
    <div class="lib-card">
      <div class="corner-accent"></div>
      <div class="lib-card-header">
        <div>
          <div class="lib-name">${esc(lib.name)}</div>
          <div class="lib-slug">${esc(lib.slug)}</div>
          ${lib.city?`<div style="font-size:11px;color:var(--text3);margin-top:3px">📍 ${esc(lib.city)}</div>`:''}
        </div>
        <span class="badge ${lib.is_active?'badge-active':'badge-inactive'}">${lib.is_active?'Aktivna':'Neaktivna'}</span>
      </div>
      <div class="lib-stats">
        <div class="lib-stat-item"><div class="lib-stat-num">${lib.books||0}</div><div class="lib-stat-lbl">Knjiga</div></div>
        <div class="lib-stat-item"><div class="lib-stat-num">${lib.members||0}</div><div class="lib-stat-lbl">Članova</div></div>
        <div class="lib-stat-item"><div class="lib-stat-num">${lib.loans||0}</div><div class="lib-stat-lbl">Posudbi</div></div>
      </div>
      <div class="lib-card-actions">
        <button class="btn btn-ghost btn-sm" onclick="openLibModal(${lib.id});showSection('libraries')" style="flex:1">✏️ Uredi</button>
        ${lib.email?`<a href="mailto:${esc(lib.email)}" class="btn btn-ghost btn-sm">✉️</a>`:''}
      </div>
    </div>
  `).join('');
}

function populateLibFilter() {
  const sel = document.getElementById('user-lib-filter');
  const uSel = document.getElementById('u-library');
  const opts = libsData.map(l => `<option value="${l.id}">${esc(l.name)}</option>`).join('');
  sel.innerHTML = '<option value="">Sve knjižnice</option>' + opts;
  uSel.innerHTML = '<option value="">— Globalni (bez knjižnice) —</option>' + opts;
}

// Library modal
function openLibModal(id=null) {
  editingLibId = id;
  document.getElementById('lib-modal-result').style.display = 'none';
  if (id) {
    const lib = libsData.find(l => l.id === id);
    if (!lib) return;
    document.getElementById('lib-modal-title').textContent = '✏️ Uredi knjižnicu';
    document.getElementById('lib-name').value = lib.name || '';
    document.getElementById('lib-slug').value = lib.slug || '';
    document.getElementById('lib-city').value = lib.city || '';
    document.getElementById('lib-address').value = lib.address || '';
    document.getElementById('lib-email').value = lib.email || '';
    document.getElementById('lib-phone').value = lib.phone || '';
    document.getElementById('lib-notes').value = lib.notes || '';
  } else {
    document.getElementById('lib-modal-title').textContent = '🏛️ Nova knjižnica';
    ['lib-name','lib-slug','lib-city','lib-address','lib-email','lib-phone','lib-notes']
      .forEach(id => document.getElementById(id).value = '');
  }
  document.getElementById('lib-modal').classList.add('show');
}
function closeLibModal() {
  document.getElementById('lib-modal').classList.remove('show');
  editingLibId = null;
}

async function saveLibrary() {
  const btn = document.getElementById('lib-save-btn');
  btn.disabled = true;
  const body = {
    name: document.getElementById('lib-name').value.trim(),
    slug: document.getElementById('lib-slug').value.trim().toLowerCase(),
    city: document.getElementById('lib-city').value.trim(),
    address: document.getElementById('lib-address').value.trim(),
    email: document.getElementById('lib-email').value.trim(),
    phone: document.getElementById('lib-phone').value.trim(),
    notes: document.getElementById('lib-notes').value.trim(),
  };
  if (!body.name || !body.slug) {
    showModalResult('lib-modal-result', '⚠️ Naziv i Slug su obavezni.', 'warn');
    btn.disabled = false; return;
  }
  try {
    const url = editingLibId ? `/admin/super/libraries/${editingLibId}` : '/admin/super/libraries';
    const method = editingLibId ? 'PUT' : 'POST';
    const r = await apiFetch(url, {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const d = await r.json();
    if (r.ok) {
      showModalResult('lib-modal-result', editingLibId ? '✅ Knjižnica ažurirana.' : '✅ Knjižnica kreirana.', 'ok');
      setTimeout(() => { closeLibModal(); loadLibsStats(); loadGlobalStats(); }, 1000);
    } else {
      showModalResult('lib-modal-result', '❌ ' + (d.detail||'Greška'), 'err');
    }
  } catch(e) { showModalResult('lib-modal-result', '❌ ' + e.message, 'err'); }
  btn.disabled = false;
}

async function toggleLib(id, isActive) {
  const action = isActive ? 'deaktivirati' : 'aktivirati';
  if (!confirm(`Sigurno ${action} ovu knjižnicu?`)) return;
  const r = await apiFetch(`/admin/super/libraries/${id}/toggle`, {method:'POST'});
  if (r.ok) { toast('Knjižnica ažurirana.', 'ok'); loadLibsStats(); loadGlobalStats(); }
  else toast('Greška pri ažuriranju.', 'err');
}

// ═══════════════════════════════════════════════════════════════
// Users
// ═══════════════════════════════════════════════════════════════
async function loadUsers() {
  try {
    const r = await apiFetch('/admin/super/users');
    if (!r.ok) return;
    usersData = await r.json();
    document.getElementById('badge-users').textContent = usersData.length;
    filterUsers();
  } catch(e) { console.error('Users error:', e); }
}

function filterUsers() {
  const q = document.getElementById('user-search').value.toLowerCase();
  const lib = document.getElementById('user-lib-filter').value;
  const role = document.getElementById('user-role-filter').value;
  usersFiltered = usersData.filter(u => {
    if (lib && String(u.library_id) !== lib) return false;
    if (role && u.role !== role) return false;
    if (!q) return true;
    return [u.username, u.full_name||'', u.email||''].some(f => f.toLowerCase().includes(q));
  });
  usersPage = 1;
  renderUsersTable();
}

function renderUsersTable() {
  const tbody = document.getElementById('users-tbody');
  if (!usersFiltered.length) {
    tbody.innerHTML = '<tr><td colspan="8"><div class="empty-state"><div class="icon">👥</div><p>Nema korisnika.</p></div></td></tr>';
    document.getElementById('users-pagination').innerHTML = '';
    return;
  }
  const start = (usersPage-1) * USERS_PAGE_SIZE;
  const recs = usersFiltered.slice(start, start + USERS_PAGE_SIZE);
  tbody.innerHTML = recs.map(u => {
    const lib = libsData.find(l => l.id === u.library_id);
    const libName = lib ? lib.name : (u.library_id ? `#${u.library_id}` : '<span style="color:var(--accent3)">🌐 Globalni</span>');
    return `<tr>
      <td>${u.id}</td>
      <td><strong style="font-family:var(--mono);font-size:11px">${esc(u.username)}</strong></td>
      <td>${esc(u.full_name||'–')}</td>
      <td style="color:var(--text2);font-size:11px">${esc(u.email||'–')}</td>
      <td><span class="badge badge-${u.role}">${u.role}</span></td>
      <td style="font-size:12px">${libName}</td>
      <td><span class="badge ${u.is_active?'badge-active':'badge-inactive'}">${u.is_active?'Aktivan':'Neaktivan'}</span></td>
      <td>
        <div class="actions-cell">
          <button class="btn btn-ghost btn-sm" onclick="openUserModal(${u.id})">✏️</button>
          <button class="btn btn-danger btn-sm" onclick="deleteUser(${u.id},'${esc(u.username)}')">🗑</button>
        </div>
      </td>
    </tr>`;
  }).join('');
  renderUsersPagination();
}

function renderUsersPagination() {
  const total = usersFiltered.length;
  const pages = Math.ceil(total / USERS_PAGE_SIZE);
  const pg = document.getElementById('users-pagination');
  if (pages <= 1) { pg.innerHTML=''; return; }
  let html = `<span class="page-info">${total} korisnika</span>`;
  for (let i=1; i<=pages; i++)
    html += `<button class="${i===usersPage?'active':''}" onclick="usersPage=${i};renderUsersTable()">${i}</button>`;
  pg.innerHTML = html;
}

// User modal
function openUserModal(id=null) {
  editingUserId = id;
  document.getElementById('user-modal-result').style.display = 'none';
  if (id) {
    const u = usersData.find(x => x.id === id);
    if (!u) return;
    document.getElementById('user-modal-title').textContent = '✏️ Uredi korisnika';
    document.getElementById('u-username').value = u.username;
    document.getElementById('u-password').value = '';
    document.getElementById('u-fullname').value = u.full_name||'';
    document.getElementById('u-email').value = u.email||'';
    document.getElementById('u-role').value = u.role;
    document.getElementById('u-library').value = u.library_id||'';
  } else {
    document.getElementById('user-modal-title').textContent = '👤 Novi korisnik';
    ['u-username','u-password','u-fullname','u-email'].forEach(id => document.getElementById(id).value='');
    document.getElementById('u-role').value = 'knjiznicar';
    document.getElementById('u-library').value = '';
  }
  document.getElementById('user-modal').classList.add('show');
}
function closeUserModal() {
  document.getElementById('user-modal').classList.remove('show');
  editingUserId = null;
}

async function saveUser() {
  const btn = document.getElementById('user-save-btn');
  btn.disabled = true;
  const body = {
    username: document.getElementById('u-username').value.trim(),
    password: document.getElementById('u-password').value,
    full_name: document.getElementById('u-fullname').value.trim(),
    email: document.getElementById('u-email').value.trim(),
    role: document.getElementById('u-role').value,
    library_id: document.getElementById('u-library').value || null,
  };
  if (!body.username) {
    showModalResult('user-modal-result','⚠️ Korisničko ime je obavezno.','warn');
    btn.disabled=false; return;
  }
  if (!editingUserId && !body.password) {
    showModalResult('user-modal-result','⚠️ Lozinka je obavezna za novog korisnika.','warn');
    btn.disabled=false; return;
  }
  try {
    const url = editingUserId ? `/admin/super/users/${editingUserId}` : '/admin/super/users';
    const method = editingUserId ? 'PUT' : 'POST';
    const r = await apiFetch(url, {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const d = await r.json();
    if (r.ok) {
      showModalResult('user-modal-result', editingUserId ? '✅ Korisnik ažuriran.' : '✅ Korisnik kreiran.', 'ok');
      setTimeout(() => { closeUserModal(); loadUsers(); loadGlobalStats(); }, 1000);
    } else showModalResult('user-modal-result','❌ ' + (d.detail||'Greška'),'err');
  } catch(e) { showModalResult('user-modal-result','❌ ' + e.message,'err'); }
  btn.disabled = false;
}

async function deleteUser(id, username) {
  if (!confirm(`Trajno obrisati korisnika "${username}"?`)) return;
  const r = await apiFetch(`/admin/super/users/${id}`, {method:'DELETE'});
  if (r.ok) { toast('Korisnik obrisan.','ok'); loadUsers(); loadGlobalStats(); }
  else toast('Greška pri brisanju.','err');
}

// ═══════════════════════════════════════════════════════════════
// Licenses
// ═══════════════════════════════════════════════════════════════
async function loadLicenses() {
  try {
    const r = await apiFetch('/admin/license/list');
    if (!r.ok) return;
    const d = await r.json();
    licData = d.records || [];
    updateLicStats();
    document.getElementById('badge-licenses').textContent =
      licData.filter(x => x.status==='expired').length || '';
    applyLicFilters();
  } catch(e) { console.error('Lic error:', e); }
}

function updateLicStats() {
  let sActive=0, sExpired=0, sRevoked=0, sExpiring=0, sTrial=0;
  for (const r of licData) {
    if (r.status==='active') sActive++;
    if (r.status==='expired') sExpired++;
    if (r.status==='revoked') sRevoked++;
    if (r.status==='active' && r.days_remaining>0 && r.days_remaining<=30) sExpiring++;
    if ((r.created_by||'').match(/trial|system/)) sTrial++;
  }
  document.getElementById('ls-total').textContent = licData.length;
  document.getElementById('ls-active').textContent = sActive;
  document.getElementById('ls-expired').textContent = sExpired;
  document.getElementById('ls-revoked').textContent = sRevoked;
  document.getElementById('ls-expiring').textContent = sExpiring;
  document.getElementById('ls-trial').textContent = sTrial;
}

function licFilter(status) {
  document.getElementById('lic-status-filter').value = status;
  applyLicFilters();
}

function applyLicFilters() {
  const q = document.getElementById('lic-search').value.toLowerCase().trim();
  const sf = document.getElementById('lic-status-filter').value;
  licFiltered = licData.filter(r => {
    if (sf==='expiring') { if (!(r.status==='active' && r.days_remaining>0 && r.days_remaining<=30)) return false; }
    else if (sf==='trial') { if (!(r.created_by||'').match(/trial|system/)) return false; }
    else if (sf && r.status!==sf) return false;
    if (!q) return true;
    return [r.email, r.status, r.machine_id||'', r.hostname||'', r.os_platform||'', r.notes||'', r.created_by||'']
      .some(f => f.toLowerCase().includes(q));
  });
  licPage = 1;
  renderLicTable();
}

function renderLicTable() {
  const tbody = document.getElementById('lic-tbody');
  const empty = document.getElementById('lic-empty');
  if (!licFiltered.length) {
    tbody.innerHTML = '';
    empty.style.display = 'block';
    document.getElementById('lic-pagination').innerHTML = '';
    return;
  }
  empty.style.display = 'none';
  const start = (licPage-1)*LIC_PAGE_SIZE;
  const recs = licFiltered.slice(start, start+LIC_PAGE_SIZE);
  tbody.innerHTML = recs.map(r => {
    const expCls = r.status==='expired' ? 'expiry-expired'
      : (r.days_remaining>0 && r.days_remaining<=30) ? 'expiry-soon' : 'expiry-ok';
    const daysLbl = r.days_remaining>0 ? `<br><small class="${expCls}">još ${r.days_remaining}d</small>` : '';
    const midShort = r.machine_id ? r.machine_id.substring(0,14)+'…' : '<span style="color:var(--text3)">floating</span>';
    const osLine = (r.os_platform||r.os_version) ? `${esc(r.os_platform||'')} ${esc(r.os_version||'')}${r.app_version?' · v'+esc(r.app_version):''}` : '';
    const revokeBtn = r.is_active
      ? `<button class="btn btn-danger btn-sm" onclick="licRevoke(${r.id})">Opozovi</button>`
      : '<span style="color:var(--text3);font-size:10px">—</span>';
    return `<tr id="licrow-${r.id}">
      <td>${r.id}</td>
      <td style="max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(r.email)}">${esc(r.email)}</td>
      <td><span class="key-mono" title="${r.license_key}" onclick="copyText('${r.license_key}')">${r.license_key.substring(0,24)}…</span></td>
      <td style="white-space:nowrap;font-size:11px">${r.issued||'–'}</td>
      <td style="white-space:nowrap;font-size:11px">${r.expiry||'–'}${daysLbl}</td>
      <td><span class="badge badge-license-${r.status}">${r.status}</span></td>
      <td class="machine-info">
        <div class="mid" title="${r.machine_id||''}" onclick="copyText('${r.machine_id||''}')" style="cursor:pointer">${midShort}</div>
        ${r.hostname?`<div>🖥 ${esc(r.hostname)}</div>`:''}
        ${osLine?`<div style="color:var(--text3);font-size:9px">${osLine}</div>`:''}
        ${(r.activation_count||0)>0?`<div style="color:var(--text3);font-size:9px">Akt: ${r.activation_count}×</div>`:''}
      </td>
      <td style="font-size:11px;color:var(--text2)">${r.last_seen||'—'}</td>
      <td><span class="note-text" title="${esc(r.notes||'')}">${esc(r.notes||'')}</span></td>
      <td>
        <div class="actions-cell">
          ${revokeBtn}
          <button class="btn btn-ghost btn-sm" onclick="licResetMid(${r.id})" title="Reset Machine ID">🔄</button>
          <button class="btn btn-ghost btn-sm" onclick="openNotes(${r.id},'${esc(r.email)}','${esc(r.notes||'')}')" title="Bilješka">✏️</button>
          <button class="btn btn-ghost btn-sm" onclick="licDelete(${r.id})" title="Obriši">🗑</button>
        </div>
      </td>
    </tr>`;
  }).join('');
  renderLicPagination();
}

function renderLicPagination() {
  const total = licFiltered.length;
  const pages = Math.ceil(total/LIC_PAGE_SIZE);
  const pg = document.getElementById('lic-pagination');
  if (pages<=1) { pg.innerHTML=''; return; }
  let html = `<span class="page-info">${total} licenci</span>`;
  for (let i=1; i<=pages; i++)
    html += `<button class="${i===licPage?'active':''}" onclick="licPage=${i};renderLicTable()">${i}</button>`;
  pg.innerHTML = html;
}

// License actions
async function generateLicense() {
  const email = document.getElementById('lic-email').value.trim();
  const days = parseInt(document.getElementById('lic-days').value) || 365;
  const mid = document.getElementById('lic-mid').value.trim();
  if (!email) { showResult('gen-result','⚠️ Unesite email!','warn'); return; }
  const fd = new FormData();
  fd.append('email', email); fd.append('days', days); fd.append('machine_id', mid);
  const r = await apiFetch('/admin/license/generate', {method:'POST', body:fd});
  const d = await r.json();
  if (r.ok) {
    showResult('gen-result',
      `✅ Ključ generiran za <strong>${esc(d.email)}</strong> (${d.days}d${d.machine_id?' · vezano':'·floating'}):<br>
       <span class="key-mono" style="max-width:100%;display:block;white-space:normal;font-family:var(--mono)" onclick="copyText('${d.key}')">${d.key}</span>
       <small style="color:var(--text3)">Kliknite na ključ za kopiranje.</small>`, 'ok');
    loadLicenses(); loadGlobalStats();
  } else showResult('gen-result','❌ '+(d.detail||r.statusText),'err');
}

async function licRevoke(id) {
  if (!confirm('Opozovati ovu licencu?')) return;
  const r = await apiFetch(`/admin/license/revoke/${id}`,{method:'POST'});
  r.ok ? (toast('Licenca opozvana.','ok'), loadLicenses()) : toast('Greška.','err');
}
async function licResetMid(id) {
  if (!confirm('Resetirati Machine ID?\n\nKorisnik može aktivirati ključ na drugom računalu.')) return;
  const r = await apiFetch(`/admin/license/reset-mid/${id}`,{method:'POST'});
  r.ok ? (toast('Machine ID resetiran.','ok'), loadLicenses()) : toast('Greška.','err');
}
async function licDelete(id) {
  if (!confirm('Trajno obrisati licencu?')) return;
  const r = await apiFetch(`/admin/license/${id}`,{method:'DELETE'});
  r.ok ? (toast('Licenca obrisana.','ok'), loadLicenses()) : toast('Greška.','err');
}
function exportLicCsv() {
  window.open('/admin/license/export/csv' + (TOKEN?`?token=${TOKEN}`:''), '_blank');
}

// Notes
function openNotes(id, email, note) {
  notesLicId = id;
  document.getElementById('notes-email-lbl').textContent = email;
  document.getElementById('notes-text').value = note || '';
  document.getElementById('notes-modal').classList.add('show');
}
function closeNotes() { document.getElementById('notes-modal').classList.remove('show'); notesLicId=null; }
async function saveNotes() {
  if (!notesLicId) return;
  const fd = new FormData(); fd.append('notes', document.getElementById('notes-text').value);
  const r = await apiFetch(`/admin/license/notes/${notesLicId}`,{method:'POST',body:fd});
  r.ok ? (closeNotes(), loadLicenses(), toast('Bilješka spremljena.','ok')) : toast('Greška.','err');
}

// System
async function debugLicenses() {
  const r = await apiFetch('/admin/license/debug');
  const d = await r.json();
  const el = document.getElementById('debug-result');
  el.className='result-msg result-ok';
  el.style.display='block';
  el.innerHTML = `<pre style="font-family:var(--mono);font-size:11px;white-space:pre-wrap">${JSON.stringify(d,null,2)}</pre>`;
}

// ═══════════════════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════════════════
function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

function copyText(txt) {
  if (!txt) return;
  navigator.clipboard.writeText(txt).then(() => toast('Kopirano!','ok'));
}

function toast(msg, type='ok') {
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = (type==='ok' ? '✓ ' : '✗ ') + msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2500);
}

function showResult(id, html, cls) {
  const map = {ok:'result-ok',err:'result-err',warn:'result-warn'};
  const el = document.getElementById(id);
  el.className = 'result-msg ' + (map[cls]||'result-ok');
  el.style.display = 'block';
  el.innerHTML = html;
}

function showModalResult(id, msg, cls) {
  showResult(id, msg, cls);
}

// Click outside modals
['lib-modal','user-modal','notes-modal'].forEach(id => {
  document.getElementById(id).addEventListener('click', function(e) {
    if (e.target === this) {
      if (id==='notes-modal') closeNotes();
      else if (id==='lib-modal') closeLibModal();
      else if (id==='user-modal') closeUserModal();
    }
  });
});
</script>
</body>
</html>
"""


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
async def super_admin_dashboard(request: Request, token: Optional[str] = Query(None)):
    """Serviramo Super Admin HTML panel — samo globalni admin."""
    require_super_admin(request, token)
    return SUPER_ADMIN_HTML


@router.get("/stats")
async def super_stats(request: Request, token: Optional[str] = Query(None)):
    """Globalne statistike svih knjižnica, korisnika, licenci."""
    require_super_admin(request, token)
    db = SessionLocal()
    try:
        today = date.today()
        libs = db.query(Library).all()
        libs_active = sum(1 for l in libs if l.is_active)
        books = db.query(Book).count()
        members_active = db.query(Member).filter(Member.is_active == True).count()
        loans_active = db.query(Loan).filter(Loan.is_returned == False).count()
        loans_overdue = db.query(Loan).filter(Loan.is_returned == False, Loan.due_date < today).count()
        users = db.query(User).count()
        lic_all = db.query(LicenseRecord).all()
        now = datetime.utcnow()
        lic_active = sum(1 for l in lic_all if l.is_active and l.expiry and l.expiry >= now)
        lic_expired = sum(1 for l in lic_all if l.expiry and l.expiry < now)
        return {
            "libraries": len(libs),
            "libraries_active": libs_active,
            "books": books,
            "members_active": members_active,
            "loans_active": loans_active,
            "loans_overdue": loans_overdue,
            "users": users,
            "lic_total": len(lic_all),
            "lic_active": lic_active,
            "lic_expired": lic_expired,
        }
    finally:
        db.close()


@router.get("/libraries-stats")
async def libraries_stats(request: Request, token: Optional[str] = Query(None)):
    """Lista knjižnica s per-tenant statistikama."""
    require_super_admin(request, token)
    db = SessionLocal()
    try:
        libs = db.query(Library).order_by(Library.id).all()
        result = []
        for lib in libs:
            books = db.query(Book).filter(Book.library_id == lib.id).count()
            members = db.query(Member).filter(Member.library_id == lib.id, Member.is_active == True).count()
            loans = db.query(Loan).filter(Loan.library_id == lib.id, Loan.is_returned == False).count()
            result.append({
                "id": lib.id,
                "name": lib.name,
                "slug": lib.slug,
                "city": lib.city,
                "address": lib.address,
                "email": lib.email,
                "phone": lib.phone,
                "is_active": lib.is_active,
                "notes": lib.notes,
                "books": books,
                "members": members,
                "loans": loans,
            })
        return result
    finally:
        db.close()


class LibraryBody(BaseModel):
    name: str
    slug: str
    city: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


@router.post("/libraries", status_code=201)
async def create_library(data: LibraryBody, request: Request, token: Optional[str] = Query(None)):
    require_super_admin(request, token)
    db = SessionLocal()
    try:
        if db.query(Library).filter(Library.slug == data.slug).first():
            raise HTTPException(status_code=400, detail=f"Slug '{data.slug}' već postoji.")
        lib = Library(**data.model_dump())
        db.add(lib)
        db.commit()
        db.refresh(lib)
        return {"id": lib.id, "name": lib.name, "slug": lib.slug}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.put("/libraries/{library_id}")
async def update_library(library_id: int, data: LibraryBody, request: Request, token: Optional[str] = Query(None)):
    require_super_admin(request, token)
    db = SessionLocal()
    try:
        lib = db.query(Library).filter(Library.id == library_id).first()
        if not lib:
            raise HTTPException(status_code=404, detail="Knjižnica nije pronađena.")
        existing = db.query(Library).filter(Library.slug == data.slug, Library.id != library_id).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Slug '{data.slug}' već koristi druga knjižnica.")
        for k, v in data.model_dump().items():
            setattr(lib, k, v)
        db.commit()
        return {"id": lib.id, "name": lib.name, "slug": lib.slug}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/libraries/{library_id}/toggle")
async def toggle_library(library_id: int, request: Request, token: Optional[str] = Query(None)):
    require_super_admin(request, token)
    db = SessionLocal()
    try:
        lib = db.query(Library).filter(Library.id == library_id).first()
        if not lib:
            raise HTTPException(status_code=404, detail="Knjižnica nije pronađena.")
        lib.is_active = not lib.is_active
        db.commit()
        return {"id": lib.id, "is_active": lib.is_active}
    finally:
        db.close()


@router.get("/users")
async def list_all_users(request: Request, token: Optional[str] = Query(None)):
    """Svi korisnici svih knjižnica."""
    require_super_admin(request, token)
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.id).all()
        return [
            {
                "id": u.id,
                "username": u.username,
                "full_name": u.full_name,
                "email": u.email,
                "role": u.role,
                "library_id": u.library_id,
                "is_active": u.is_active,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "plain_password": decrypt_password(u.plain_password),  # Super admin vidi sve
            }
            for u in users
        ]
    finally:
        db.close()


class UserBody(BaseModel):
    username: str
    password: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: str = "knjiznicar"
    library_id: Optional[int] = None


@router.post("/users", status_code=201)
async def create_user(data: UserBody, request: Request, token: Optional[str] = Query(None)):
    require_super_admin(request, token)
    if not data.password:
        raise HTTPException(status_code=400, detail="Lozinka je obavezna.")
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == data.username).first():
            raise HTTPException(status_code=400, detail=f"Korisničko ime '{data.username}' već postoji.")
        try:
            role = UserRole(data.role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Nepoznata rola: {data.role}")
        user = User(
            username=data.username,
            full_name=data.full_name,
            email=data.email,
            role=role,
            library_id=data.library_id,
            hashed_password=hash_password(data.password),
            plain_password=encrypt_password(data.password),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return {"id": user.id, "username": user.username}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.put("/users/{user_id}")
async def update_user(user_id: int, data: UserBody, request: Request, token: Optional[str] = Query(None)):
    require_super_admin(request, token)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Korisnik nije pronađen.")
        dup = db.query(User).filter(User.username == data.username, User.id != user_id).first()
        if dup:
            raise HTTPException(status_code=400, detail=f"Username '{data.username}' već postoji.")
        user.username = data.username
        user.full_name = data.full_name
        user.email = data.email
        try:
            user.role = UserRole(data.role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Nepoznata rola: {data.role}")
        user.library_id = data.library_id
        if data.password:
            user.hashed_password = hash_password(data.password)
            user.plain_password = encrypt_password(data.password)
        db.commit()
        return {"id": user.id, "username": user.username}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, request: Request, token: Optional[str] = Query(None)):
    require_super_admin(request, token)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Korisnik nije pronađen.")
        if user.username == "admin":
            raise HTTPException(status_code=400, detail="Ne možete obrisati glavnog admina.")
        username = user.username
        db.delete(user)
        db.commit()
        return {"ok": True, "deleted": username}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
