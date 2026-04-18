"""
app/routes/websocket_router.py – WebSocket endpoint s JWT autentikacijom
Verzija: 8.3 (finalni ispravci)

ISPRAVCI v8.3 (nadogradnja na v8.2 ispravke):
  1. KRITIČNO: `token = None` odmah nakon potpisa funkcije brisao je token iz
     query parametra — uklonjeno. Header-first logika sada radi ispravno.
  2. KRITIČNO: Hardkodirani SECRET_KEY zamijenjen importom iz app.auth —
     osigurava konzistentnost s env varijablom KNJIZNICA_SECRET_KEY.
  3. KRITIČNO: `get_online_users` koristio je broadcast() (šalje svima) umjesto
     send_personal_message() (šalje samo tražitelju) — ispravljeno.
  4. KRITIČNO: _send_online_users slao je "online_users" ključ — promijenjen u
     "users" da se sinkronizira s broadcast_active_users() i Flutter parserima.
  5. `manager = manager` self-assignment na dnu datoteke — uklonjeno (NoOp).
  6. `admin_websocket` nije imao JWT provjeru — dodana.
  7. `_cleanup_client` pretvoren u async funkciju — await umjesto create_task
     iz sync konteksta.
  8. CRLF → LF line endings.
"""

import json
from datetime import datetime
from typing import Dict

from app.auth import ALGORITHM, SECRET_KEY
from app.database import SessionLocal
from app.rate_limiter import rate_limiter
from app.websocket import (
    broadcast_active_users,
    manager,
    notify_user_connected,
    notify_user_disconnected,
)
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt

router = APIRouter()

# Presence: client_id → {user_id, username, role, client_type, connected_at, ...}
online_users: Dict[str, dict] = {}


# ── GLAVNI WebSocket ENDPOINT ─────────────────────────────────────────────────

@router.websocket("/ws/notifications")
async def websocket_endpoint(
    websocket: WebSocket,
    client_id: str = Query(..., description="Jedinstveni ID klijenta (user_id:client_type)"),
    client_type: str = Query("desktop", description="Tip klijenta (desktop, web, admin)"),
    user_id: str = Query(None, description="ID korisnika"),
    token: str = Query(None, description="JWT token (fallback ako nema Authorization headera)"),
):
    """
    WebSocket endpoint s JWT autentikacijom.

    Prioritet tokena:
      1. Authorization: Bearer <token> header
      2. ?token=<token> query parametar
      3. Anonimni pristup (lokalni dev)
    """
    print(f"🔌 WS connect: client_id={client_id}, type={client_type}, "
          f"user_id={user_id}, token_in_query={bool(token)}")

    # ── Izvuci token – header ima prioritet ──────────────────────────────
    # ISPRAVAK: NE radimo `token = None` (to je bio bug koji je brisao query token)
    auth_header = websocket.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
        print(f"🔑 Token iz HEADERA: {token[:20]}...")
    elif token:
        print(f"🔑 Token iz QUERY: {token[:20]}...")
    else:
        print("✅ Anonimna WS veza (lokalni dev)")

    # ── JWT provjera ─────────────────────────────────────────────────────
    current_user = None
    if token:
        try:
            # ISPRAVAK: SECRET_KEY iz app.auth — ne hardkodirani string
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username = payload.get("sub")
            if not username:
                await websocket.close(code=1008, reason="Invalid token payload")
                return

            db = SessionLocal()
            try:
                from app.models.user import User
                current_user = db.query(User).filter(User.username == username).first()
            finally:
                db.close()

            if not current_user or not current_user.is_active:
                await websocket.close(code=1008, reason="User inactive or not found")
                return

            print(f"✅ JWT OK: {username} ({current_user.role})")

        except JWTError as exc:
            print(f"❌ JWT greška: {exc}")
            await websocket.close(code=1008, reason="Invalid token")
            return

    # ── Spajanje ──────────────────────────────────────────────────────────
    await manager.connect(websocket, client_id, client_type)

    # Presence tracking
    if user_id and current_user:
        online_users[client_id] = {
            "user_id": user_id,
            "username": current_user.username,
            "role": current_user.role,
            "client_type": client_type,
            "connected_at": datetime.now().isoformat(),
        }
        await notify_user_connected(user_id, client_type)
        await broadcast_active_users()

    await manager.start_heartbeat(client_id, websocket)

    # ── Glavna petlja ─────────────────────────────────────────────────────
    try:
        while True:
            data = await websocket.receive_text()

            # Rate limiting
            allowed, retry_after = rate_limiter.is_allowed(client_id)
            if not allowed:
                await manager.send_personal_message(websocket, {
                    "type": "rate_limit_exceeded",
                    "retry_after": retry_after,
                    "message": f"Prekoračen limit ({rate_limiter.max_messages}/"
                               f"{rate_limiter.window_seconds}s)",
                })
                continue

            # Parsiranje poruke
            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                await manager.send_personal_message(
                    websocket, {"type": "error", "message": "Invalid JSON"}
                )
                continue

            msg_type = message.get("type")

            # ── Protokol ────────────────────────────────────────────────
            if msg_type == "pong":
                manager.record_pong(client_id)
                continue

            if msg_type == "ping":
                if client_id in online_users:
                    online_users[client_id]["last_seen"] = datetime.now().isoformat()
                await manager.send_personal_message(websocket, {"type": "pong"})
                continue

            # ── Chat ─────────────────────────────────────────────────────
            if msg_type == "chat_message":
                sender = message.get("sender_name", "Anonimno")
                await manager.broadcast({
                    "type": "new_message",
                    "message": {
                        "sender": sender,
                        "text": message.get("message", ""),
                        "timestamp": datetime.now().isoformat(),
                    },
                })

            # ── Online korisnici ──────────────────────────────────────────
            if msg_type == "get_online_users":
                # ISPRAVAK: send_personal_message samo tražitelju, ne broadcast svima
                await _send_online_users(websocket)

    except WebSocketDisconnect:
        await _cleanup_client(client_id)


async def _send_online_users(websocket: WebSocket):
    """
    Pošalji listu online korisnika jednom klijentu.
    ISPRAVAK v8.3: ključ promijenjen iz "online_users" u "users" —
    mora biti konzistentan s broadcast_active_users() u websocket.py
    i s Flutter parserom (json['users']).
    """
    try:
        users_list = _build_online_users_list()
        await manager.send_personal_message(websocket, {
            "type": "active_users",
            "users": [u.model_dump() for u in users_list],   # ← "users", ne "online_users"
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as exc:
        print(f"Greška pri slanju online korisnika: {exc}")


def _build_online_users_list():
    """Izgradi listu OnlineUserOut objekata iz online_users rječnika."""
    from app.schemas.online_user import OnlineUserOut
    result = []
    for cid, udata in online_users.items():
        try:
            result.append(OnlineUserOut(
                user_id=int(udata["user_id"]),
                username=udata["username"],
                role=udata["role"],
                client_type=udata["client_type"],
                connected_at=datetime.fromisoformat(udata["connected_at"]),
                last_seen=(
                    datetime.fromisoformat(udata["last_seen"])
                    if "last_seen" in udata else None
                ),
            ))
        except (ValueError, KeyError, TypeError) as exc:
            print(f"Greška pri parsiranju online korisnika {cid}: {exc}")
    return result


async def _cleanup_client(client_id: str):
    """
    Ukloni klijenta iz svih registara pri odspajanju.
    ISPRAVAK: async funkcija — direktno await umjesto asyncio.create_task
    iz sync konteksta.
    """
    user_data = online_users.pop(client_id, None)
    manager.disconnect(client_id)

    if user_data:
        await notify_user_disconnected(user_data["user_id"])
        await broadcast_active_users()


# ── ADMIN WebSocket ───────────────────────────────────────────────────────────

@router.websocket("/ws/admin")
async def admin_websocket(
    websocket: WebSocket,
    client_id: str = Query(...),
    token: str = Query(..., description="JWT token obavezan za admin WS"),
):
    """
    Admin WebSocket – zahtijeva JWT s admin ulogom.
    ISPRAVAK: dodana JWT provjera (ranije je bila izostavljena).
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        db = SessionLocal()
        try:
            from app.models.user import User, UserRole
            user = db.query(User).filter(User.username == username).first()
        finally:
            db.close()

        if not user or user.role != UserRole.admin:
            await websocket.close(code=1008, reason="Admin only")
            return
    except JWTError:
        await websocket.close(code=1008, reason="Invalid token")
        return

    await manager.connect(websocket, client_id, "admin")

    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                await manager.send_personal_message(
                    websocket, {"type": "error", "message": "Invalid JSON"}
                )
                continue

            msg_type = message.get("type")

            if msg_type == "ping":
                await manager.send_personal_message(websocket, {"type": "pong"})

            elif msg_type == "get_stats":
                await manager.send_personal_message(websocket, {
                    "type": "stats",
                    "data": {
                        "connections": manager.get_connection_count(),
                        "online_users": len(online_users),
                        "connections_by_type": manager.get_connections_by_type(),
                        "heartbeat_stats": manager.get_heartbeat_stats(),
                    },
                    "timestamp": datetime.now().isoformat(),
                })

    except WebSocketDisconnect:
        manager.disconnect(client_id)


# ── HTTP STATS ────────────────────────────────────────────────────────────────

@router.get("/ws/stats", tags=["WebSocket"])
def ws_stats():
    """HTTP endpoint za statistike WebSocket veza."""
    return {
        "connections": manager.get_connection_count(),
        "connections_by_type": manager.get_connections_by_type(),
        "online_users": len(online_users),
        "online_users_list": [
            {
                "user_id": d["user_id"],
                "username": d["username"],
                "role": d["role"],
                "client_type": d["client_type"],
                "connected_at": d["connected_at"],
            }
            for d in online_users.values()
        ],
        "rate_limiter": rate_limiter.get_stats(),
        "heartbeat_stats": manager.get_heartbeat_stats(),
    }
