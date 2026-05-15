"""
Real-time Data Synchronization Router for Knjižnica API
WebSocket endpoint za sinkronizaciju podataka između klijenata.
"""

import json
from datetime import datetime
from typing import Dict, List

from app.rate_limiter import sync_rate_limiter
from app.websocket import manager, notify_data_update
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

router = APIRouter()

# ─── SYNC SESSIONS ────────────────────────────────────────────────────────────

# Pohrana aktivnih sync sesija
sync_sessions: Dict[str, dict] = {}

# Posljednje promjene po entitetima
recent_changes: Dict[str, List[dict]] = {
    "books": [],
    "members": [],
    "loans": [],
    "users": [],
}

MAX_RECENT_CHANGES = 100  # Maksimalno pohranjenih promjena


# ─── WEBSOCKET ENDPOINT ───────────────────────────────────────────────────────

@router.websocket("/ws/sync")
async def sync_endpoint(
    websocket: WebSocket,
    client_id: str = Query(..., description="Jedinstveni ID klijenta"),
    user_id: str = Query(None, description="ID korisnika"),
    client_type: str = Query("desktop", description="Tip klijenta")
):
    """
    WebSocket endpoint for real-time data synchronization.

    Omogućuje klijentima:
    - Primanje ažuriranja podataka u real-time
    - Slanje promjena koje se broadcastaju drugima
    - Dohvat posljednjih promjena pri spajanju
    """
    print(f"Sync veza: client_id={client_id}, user_id={user_id}")

    # Spoji klijenta
    await manager.connect(websocket, client_id, f"sync_{client_type}")

    # Kreiraj sync sesiju
    sync_sessions[client_id] = {
        "user_id": user_id,
        "client_id": client_id,
        "client_type": client_type,
        "connected_at": datetime.now().isoformat(),
        "last_sync": datetime.now().isoformat(),
        "subscribed_entities": [],
    }

    try:
        # Pošalji dobrodošlicu s posljednjim promjenama
        await manager.send_personal_message(websocket, {
            "type": "sync_welcome",
            "message": "Spojen na real-time sync",
            "recent_changes": {
                entity: changes[-10:]  # Posljednjih 10 promjena
                for entity, changes in recent_changes.items()
                if changes
            },
            "timestamp": datetime.now().isoformat()
        })

        # Glavna petlja
        while True:
            data = await websocket.receive_text()

            # Provjeri rate limit
            allowed, retry_after = sync_rate_limiter.is_allowed(client_id)
            if not allowed:
                await manager.send_personal_message(websocket, {
                    "type": "rate_limit_exceeded",
                    "retry_after": retry_after,
                    "message": f"Sync rate limit exceeded. Pričekajte {retry_after}s"
                })
                continue

            try:
                message = json.loads(data)
                msg_type = message.get("type")

                if msg_type == "subscribe":
                    # Pretplati se na određene entitete
                    entities = message.get("entities", [])
                    if client_id in sync_sessions:
                        sync_sessions[client_id]["subscribed_entities"] = entities
                    await manager.send_personal_message(websocket, {
                        "type": "subscribed",
                        "entities": entities,
                        "timestamp": datetime.now().isoformat()
                    })

                elif msg_type == "sync_data":
                    # Klijent šalje ažuriranje
                    entity = message.get("entity")
                    action = message.get("action")
                    data_payload = message.get("data")
                    source = message.get("source", client_id)

                    if entity and action and data_payload:
                        # Spremi promjenu
                        change = {
                            "entity": entity,
                            "action": action,
                            "data": data_payload,
                            "source": source,
                            "user_id": user_id,
                            "timestamp": datetime.now().isoformat()
                        }

                        if entity in recent_changes:
                            recent_changes[entity].append(change)
                            # Ograniči broj pohranjenih promjena
                            if len(recent_changes[entity]) > MAX_RECENT_CHANGES:
                                recent_changes[entity] = \
                                    recent_changes[entity][-MAX_RECENT_CHANGES:]

                        # Broadcastaj promjenu drugim klijentima
                        await notify_data_update(
                            entity=entity,
                            action=action,
                            data=data_payload,
                            source=source
                        )

                        # Potvrdi klijentu
                        await manager.send_personal_message(websocket, {
                            "type": "sync_confirmed",
                            "entity": entity,
                            "action": action,
                            "timestamp": datetime.now().isoformat()
                        })

                elif msg_type == "get_recent_changes":
                    # Dohvati posljednje promjene
                    entity_filter = message.get("entity")
                    since = message.get("since")  # ISO format timestamp

                    changes = []
                    if entity_filter:
                        changes = recent_changes.get(entity_filter, [])
                    else:
                        for entity_changes in recent_changes.values():
                            changes.extend(entity_changes)

                    # Filtriraj po vremenu ako je navedeno
                    if since:
                        try:
                            since_dt = datetime.fromisoformat(since)
                            changes = [
                                c for c in changes
                                if datetime.fromisoformat(c["timestamp"]) > since_dt
                            ]
                        except:
                            pass

                    # Sortiraj po vremenu
                    changes.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

                    await manager.send_personal_message(websocket, {
                        "type": "recent_changes",
                        "changes": changes[-20:],  # Vrati posljednjih 20
                        "count": len(changes),
                        "timestamp": datetime.now().isoformat()
                    })

                elif msg_type == "ping":
                    # Odgovori na ping
                    await manager.send_personal_message(websocket, {
                        "type": "pong",
                        "timestamp": datetime.now().isoformat()
                    })

            except json.JSONDecodeError:
                await manager.send_personal_message(websocket, {
                    "type": "error",
                    "message": "Invalid JSON"
                })

    except WebSocketDisconnect:
        manager.disconnect(client_id)

        # Ukloni sync sesiju
        if client_id in sync_sessions:
            del sync_sessions[client_id]


# ─── REST ENDPOINTS ───────────────────────────────────────────────────────────

@router.get("/sync/recent-changes")
def get_recent_changes(
    entity: str = None,
    since: str = None,
    limit: int = 50
):
    """
    REST endpoint za dohvat posljednjih promjena.

    Args:
        entity: Filtriraj po entitetu (books, members, loans, users)
        since: Filtriraj po vremenu (ISO format)
        limit: Maksimalan broj rezultata
    """
    changes = []

    if entity:
        changes = recent_changes.get(entity, [])
    else:
        for entity_changes in recent_changes.values():
            changes.extend(entity_changes)

    # Filtriraj po vremenu
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            changes = [
                c for c in changes
                if datetime.fromisoformat(c["timestamp"]) > since_dt
            ]
        except:
            pass

    # Sortiraj i ograniči
    changes.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    return {
        "changes": changes[:limit],
        "total": len(changes),
        "timestamp": datetime.now().isoformat()
    }


@router.get("/sync/stats")
def get_sync_stats():
    """
    Statistike sync sustava.
    """
    return {
        "active_sessions": len(sync_sessions),
        "sessions": list(sync_sessions.values()),
        "recent_changes_count": {
            entity: len(changes)
            for entity, changes in recent_changes.items()
        },
        "timestamp": datetime.now().isoformat()
    }


@router.delete("/sync/recent-changes")
def clear_recent_changes(entity: str = None):
    """
    Obriši povijest promjena.

    Args:
        entity: Ako je navedeno, briše samo za taj entitet
    """
    if entity:
        if entity in recent_changes:
            count = len(recent_changes[entity])
            recent_changes[entity] = []
            return {
                "message": f"Obrisano {count} promjena za {entity}",
                "entity": entity
            }
    else:
        total = sum(len(c) for c in recent_changes.values())
        for entity in recent_changes:
            recent_changes[entity] = []
        return {
            "message": f"Obrisano {total} promjena",
            "entities": list(recent_changes.keys())
        }

    return {"message": "No changes to clear"}
