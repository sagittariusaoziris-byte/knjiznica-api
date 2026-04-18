"""
Chat/Komentari Router for Knjižnica API
Real-time komunikacija između korisnika i knjižničara.
"""

import json
from datetime import datetime
from typing import Dict, List, Optional

from app.rate_limiter import chat_rate_limiter
from app.websocket import manager
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

router = APIRouter()

# ─── CHAT STORAGE ─────────────────────────────────────────────────────────────

# Aktivne chat sobe
chat_rooms: Dict[str, dict] = {}

# Poruke po sobama (posljednjih 100)
room_messages: Dict[str, List[dict]] = {}

# Korisnici po sobama
room_users: Dict[str, set] = {}

MAX_MESSAGES_PER_ROOM = 100


# ─── MODELS ───────────────────────────────────────────────────────────────────

class ChatMessage:
    """Chat poruka."""

    def __init__(
        self,
        room_id: str,
        sender_id: str,
        sender_name: str,
        message: str,
        message_type: str = "text"
    ):
        self.room_id = room_id
        self.sender_id = sender_id
        self.sender_name = sender_name
        self.message = message
        self.message_type = message_type
        self.timestamp = datetime.now().isoformat()
        self.is_read = False

    def to_dict(self) -> dict:
        return {
            "room_id": self.room_id,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "message": self.message,
            "message_type": self.message_type,
            "timestamp": self.timestamp,
            "is_read": self.is_read
        }


# ─── WEBSOCKET ENDPOINTS ──────────────────────────────────────────────────────

@router.websocket("/ws/chat/{room_id}")
async def chat_endpoint(
    websocket: WebSocket,
    room_id: str,
    user_id: str = Query(..., description="ID korisnika"),
    user_name: str = Query(..., description="Ime korisnika"),
    user_role: str = Query("citac", description="Uloga korisnika")
):
    """
    WebSocket endpoint za chat sobu.

    Omogućuje:
    - Slanje i primanje poruka u real-time
    - Obavijesti o ulasku/izlasku korisnika
    - Povijest poruka pri spajanju
    """
    print(f"Chat veza: room={room_id}, user={user_name} ({user_role})")

    # Spoji klijenta
    client_id = f"chat_{room_id}_{user_id}"
    await manager.connect(websocket, client_id, "chat")

    # Kreiraj sobu ako ne postoji
    if room_id not in chat_rooms:
        chat_rooms[room_id] = {
            "room_id": room_id,
            "created_at": datetime.now().isoformat(),
            "message_count": 0,
        }
        room_messages[room_id] = []
        room_users[room_id] = set()

    # Dodaj korisnika u sobu
    room_users[room_id].add(user_id)

    # Kreiraj sesiju
    session = {
        "user_id": user_id,
        "user_name": user_name,
        "user_role": user_role,
        "room_id": room_id,
        "joined_at": datetime.now().isoformat(),
    }

    try:
        # Pošalji dobrodošlicu s poviješću
        await manager.send_personal_message(websocket, {
            "type": "chat_welcome",
            "room_id": room_id,
            "user_name": user_name,
            "recent_messages": room_messages[room_id][-20:],  # Posljednjih 20
            "active_users": list(room_users[room_id]),
            "timestamp": datetime.now().isoformat()
        })

        # Obavijesti ostale da je korisnik ušao
        await manager.broadcast({
            "type": "user_joined",
            "room_id": room_id,
            "user_id": user_id,
            "user_name": user_name,
            "timestamp": datetime.now().isoformat()
        }, client_type="chat")

        # Glavna petlja
        while True:
            data = await websocket.receive_text()

            # Provjeri rate limit
            allowed, retry_after = chat_rate_limiter.is_allowed(client_id)
            if not allowed:
                await manager.send_personal_message(websocket, {
                    "type": "rate_limit_exceeded",
                    "retry_after": retry_after,
                    "message": f"Chat rate limit exceeded"
                })
                continue

            try:
                message = json.loads(data)
                msg_type = message.get("type")

                if msg_type == "chat_message":
                    # Korisnik šalje poruku
                    text = message.get("message", "")
                    msg_type_inner = message.get("message_type", "text")

                    if text.strip():
                        # Kreiraj poruku
                        chat_msg = ChatMessage(
                            room_id=room_id,
                            sender_id=user_id,
                            sender_name=user_name,
                            message=text,
                            message_type=msg_type_inner
                        )

                        # Spremi poruku
                        room_messages[room_id].append(chat_msg.to_dict())
                        chat_rooms[room_id]["message_count"] += 1

                        # Ograniči broj poruka
                        if len(room_messages[room_id]) > MAX_MESSAGES_PER_ROOM:
                            room_messages[room_id] = \
                                room_messages[room_id][-MAX_MESSAGES_PER_ROOM:]

                        # Broadcastaj svima u sobi
                        await manager.broadcast({
                            "type": "new_message",
                            "room_id": room_id,
                            "message": chat_msg.to_dict(),
                            "timestamp": datetime.now().isoformat()
                        }, client_type="chat")

                elif msg_type == "typing":
                    # Korisnik tipka
                    await manager.broadcast({
                        "type": "user_typing",
                        "room_id": room_id,
                        "user_id": user_id,
                        "user_name": user_name,
                        "timestamp": datetime.now().isoformat()
                    }, client_type="chat")

                elif msg_type == "get_messages":
                    # Dohvati poruke
                    since = message.get("since")
                    limit = message.get("limit", 50)

                    messages = room_messages.get(room_id, [])

                    if since:
                        try:
                            since_dt = datetime.fromisoformat(since)
                            messages = [
                                m for m in messages
                                if datetime.fromisoformat(m["timestamp"]) > since_dt
                            ]
                        except:
                            pass

                    await manager.send_personal_message(websocket, {
                        "type": "messages",
                        "room_id": room_id,
                        "messages": messages[-limit:],
                        "count": len(messages),
                        "timestamp": datetime.now().isoformat()
                    })

                elif msg_type == "ping":
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

        # Ukloni korisnika iz sobe
        if room_id in room_users and user_id in room_users[room_id]:
            room_users[room_id].remove(user_id)

        # Obavijesti ostale da je korisnik izašao
        await manager.broadcast({
            "type": "user_left",
            "room_id": room_id,
            "user_id": user_id,
            "user_name": user_name,
            "timestamp": datetime.now().isoformat()
        }, client_type="chat")


# ─── REST ENDPOINTS ───────────────────────────────────────────────────────────

@router.get("/chat/rooms")
def get_chat_rooms():
    """
    Dohvati sve aktivne chat sobe.
    """
    rooms = []
    for room_id, room_data in chat_rooms.items():
        rooms.append({
            **room_data,
            "active_users": len(room_users.get(room_id, set())),
            "users": list(room_users.get(room_id, set())),
        })
    return {
        "rooms": rooms,
        "total": len(rooms),
        "timestamp": datetime.now().isoformat()
    }


@router.get("/chat/rooms/{room_id}/messages")
def get_room_messages(
    room_id: str,
    since: str = None,
    limit: int = 50
):
    """
    Dohvati poruke iz chat sobe.

    Args:
        room_id: ID chat sobe
        since: Filtriraj po vremenu (ISO format)
        limit: Maksimalan broj rezultata
    """
    messages = room_messages.get(room_id, [])

    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            messages = [
                m for m in messages
                if datetime.fromisoformat(m["timestamp"]) > since_dt
            ]
        except:
            pass

    return {
        "room_id": room_id,
        "messages": messages[-limit:],
        "total": len(messages),
        "timestamp": datetime.now().isoformat()
    }


@router.get("/chat/rooms/{room_id}/users")
def get_room_users(room_id: str):
    """
    Dohvati korisnike u chat sobi.
    """
    users = list(room_users.get(room_id, set()))
    return {
        "room_id": room_id,
        "users": users,
        "count": len(users),
        "timestamp": datetime.now().isoformat()
    }


@router.post("/chat/rooms/{room_id}/message")
def send_room_message(
    room_id: str,
    user_id: str,
    user_name: str,
    message: str,
    message_type: str = "text"
):
    """
    Pošalji poruku u chat sobu (REST API).

    Korisno za klijente koji ne koriste WebSocket.
    """
    if room_id not in chat_rooms:
        chat_rooms[room_id] = {
            "room_id": room_id,
            "created_at": datetime.now().isoformat(),
            "message_count": 0,
        }
        room_messages[room_id] = []
        room_users[room_id] = set()

    chat_msg = ChatMessage(
        room_id=room_id,
        sender_id=user_id,
        sender_name=user_name,
        message=message,
        message_type=message_type
    )

    room_messages[room_id].append(chat_msg.to_dict())
    chat_rooms[room_id]["message_count"] += 1

    return {
        "success": True,
        "message": chat_msg.to_dict()
    }


@router.delete("/chat/rooms/{room_id}")
def delete_chat_room(room_id: str):
    """
    Obriši chat sobu.
    """
    if room_id in chat_rooms:
        del chat_rooms[room_id]
    if room_id in room_messages:
        del room_messages[room_id]
    if room_id in room_users:
        del room_users[room_id]

    return {"success": True, "message": f"Room {room_id} deleted"}
