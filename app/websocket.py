"""
app/websocket.py – WebSocket ConnectionManager i helper funkcije
Verzija: 8.1 (fix)
"""

import asyncio
import time
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from fastapi import WebSocket


class PriorityLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


def _now() -> str:
    return datetime.now().isoformat()


class ConnectionManager:
    """Upravlja WebSocket vezama."""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_types: Dict[str, str] = {}
        self._heartbeat_tasks: Dict[str, asyncio.Task] = {}
        self._last_pong: Dict[str, float] = {}

    async def connect(self, websocket: WebSocket, client_id: str, client_type: str = "desktop"):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.connection_types[client_id] = client_type
        self._last_pong[client_id] = time.time()
        print(f"WS connected: {client_id} ({client_type})")

    def disconnect(self, client_id: str):
        self.active_connections.pop(client_id, None)
        self.connection_types.pop(client_id, None)
        self._last_pong.pop(client_id, None)
        self.stop_heartbeat(client_id)
        print(f"WS disconnected: {client_id}")

    async def send_personal_message(self, websocket: WebSocket, data: dict):
        try:
            await websocket.send_json(data)
        except Exception as exc:
            print(f"Greška pri slanju osobne poruke: {exc}")

    async def broadcast(self, data: dict, client_type: Optional[str] = None):
        connections = list(self.active_connections.items())
        for client_id, websocket in connections:
            if client_type and self.connection_types.get(client_id) != client_type:
                continue
            try:
                await websocket.send_json(data)
            except Exception as exc:
                print(f"Greška pri broadcastu za {client_id}: {exc}")

    async def start_heartbeat(self, client_id: str, websocket: WebSocket, interval: int = 30):
        async def _heartbeat():
            while client_id in self.active_connections:
                await asyncio.sleep(interval)
                try:
                    elapsed = time.time() - self._last_pong.get(client_id, 0)
                    if elapsed > interval * 2:
                        self.disconnect(client_id)
                        break
                    await websocket.send_json({"type": "ping", "timestamp": _now()})
                except Exception:
                    break
        task = asyncio.create_task(_heartbeat())
        self._heartbeat_tasks[client_id] = task

    def stop_heartbeat(self, client_id: str):
        task = self._heartbeat_tasks.pop(client_id, None)
        if task:
            task.cancel()

    def record_pong(self, client_id: str):
        self._last_pong[client_id] = time.time()

    def get_connection_count(self) -> int:
        return len(self.active_connections)

    def get_connections_by_type(self) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for ct in self.connection_types.values():
            result[ct] = result.get(ct, 0) + 1
        return result

    def get_heartbeat_stats(self) -> dict:
        return {
            "active_heartbeats": len(self._heartbeat_tasks),
            "clients": list(self._heartbeat_tasks.keys()),
        }


# ── Singleton ─────────────────────────────────────────────────────────────────
manager = ConnectionManager()


class NotificationTypes:
    BOOK_BORROWED = "book_borrowed"
    BOOK_RETURNED = "book_returned"
    LOAN_OVERDUE = "loan_overdue"
    RESERVATION_READY = "reservation_ready"
    STATS_UPDATED = "stats_updated"
    NOTIFICATION = "notification"
    LOAN_STATUS = "loan_status"
    DATA_UPDATE = "data_update"
    AUDIT_LOG = "audit_log"
    USER_CONNECTED = "user_connected"
    USER_DISCONNECTED = "user_disconnected"
    ACTIVE_USERS = "active_users"
    ERROR = "error"
    SYSTEM_ALERT = "system_alert"


async def notify_book_returned(book_id: int, book_title: str, member_name: str, loan_id: int):
    await manager.broadcast({"type": NotificationTypes.BOOK_RETURNED, "book_id": book_id,
        "book_title": book_title, "member_name": member_name, "loan_id": loan_id, "timestamp": _now()})


async def notify_book_borrowed(book_id: int, book_title: str, member_name: str, loan_id: int):
    await manager.broadcast({"type": NotificationTypes.BOOK_BORROWED, "book_id": book_id,
        "book_title": book_title, "member_name": member_name, "loan_id": loan_id, "timestamp": _now()})


async def notify_loan_overdue(loan_id: int, book_title: str, member_name: str, days_overdue: int):
    await manager.broadcast({"type": NotificationTypes.LOAN_OVERDUE, "loan_id": loan_id,
        "book_title": book_title, "member_name": member_name, "days_overdue": days_overdue, "timestamp": _now()})


async def notify_reservation_ready(reservation_id: int, book_title: str, member_name: str):
    await manager.broadcast({"type": NotificationTypes.RESERVATION_READY, "reservation_id": reservation_id,
        "book_title": book_title, "member_name": member_name, "timestamp": _now()})


async def notify_stats_updated(stats: dict):
    await manager.broadcast({"type": NotificationTypes.STATS_UPDATED, "stats": stats, "timestamp": _now()})


async def notify_notification(title: str, message: str, priority: str = PriorityLevel.medium,
                               action_url: Optional[str] = None, user_id: Optional[int] = None):
    await manager.broadcast({"type": NotificationTypes.NOTIFICATION, "title": title,
        "message": message, "priority": priority, "action_url": action_url,
        "user_id": user_id, "timestamp": _now()})


async def notify_loan_status(loan_id: int, member_id: int, status: str,
                              due_date: str = None, return_date: str = None):
    await manager.broadcast({"type": NotificationTypes.LOAN_STATUS, "loan_id": loan_id,
        "member_id": member_id, "status": status, "due_date": due_date,
        "return_date": return_date, "timestamp": _now()})


async def notify_data_update(entity: str, action: str, data: dict):
    await manager.broadcast({"type": NotificationTypes.DATA_UPDATE, "entity": entity,
        "action": action, "data": data, "timestamp": _now()})


async def notify_audit_log(source: str, entity_type: str, entity_id: int,
                            action: str, details: dict = None):
    await manager.broadcast({"type": NotificationTypes.AUDIT_LOG, "source": source,
        "entity_type": entity_type, "entity_id": entity_id, "action": action,
        "details": details or {}, "timestamp": _now()})


async def notify_user_connected(user_id: str, client_type: str = "desktop"):
    await manager.broadcast({"type": NotificationTypes.USER_CONNECTED, "user_id": user_id,
        "client_type": client_type, "timestamp": _now()})


async def notify_user_disconnected(user_id: str):
    await manager.broadcast({"type": NotificationTypes.USER_DISCONNECTED,
        "user_id": user_id, "timestamp": _now()})


async def broadcast_active_users():
    try:
        from app.routes.websocket_router import online_users
        users_list = [{"user_id": d.get("user_id"), "username": d.get("username"),
            "role": d.get("role"), "client_type": d.get("client_type"),
            "connected_at": d.get("connected_at")} for d in online_users.values()]
    except ImportError:
        users_list = []
    await manager.broadcast({"type": NotificationTypes.ACTIVE_USERS,
        "users": users_list, "count": len(users_list), "timestamp": _now()})


async def send_error(websocket: WebSocket, code: str, message: str):
    await manager.send_personal_message(websocket, {"type": NotificationTypes.ERROR,
        "code": code, "message": message, "timestamp": _now()})


async def send_priority_notification(title: str, message: str,
                                      priority: str = PriorityLevel.medium,
                                      bypass_batch: bool = False):
    if priority == PriorityLevel.urgent or bypass_batch:
        await notify_notification(title=title, message=message, priority=priority)
    else:
        notification_batcher.add(title=title, message=message, priority=priority)


async def broadcast_urgent(message: str, title: str = "Hitno"):
    await notify_notification(title=title, message=message, priority=PriorityLevel.urgent)


async def notify_loan_overdue_urgent(loan_id: int, book_title: str, member_name: str, days_overdue: int):
    await notify_loan_overdue(loan_id, book_title, member_name, days_overdue)
    await broadcast_urgent(message=f"Kasni povrat: '{book_title}' ({member_name}, {days_overdue} dana)",
                           title="Kašnjenje povrata")


async def notify_system_alert(message: str, priority: str = PriorityLevel.high):
    await manager.broadcast({"type": NotificationTypes.SYSTEM_ALERT,
        "message": message, "priority": priority, "timestamp": _now()})


class NotificationBatcher:
    def __init__(self, delay: float = 2.0):
        self._batches: Dict[str, List[dict]] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self.delay = delay

    def add(self, title: str, message: str, priority: str = PriorityLevel.medium):
        key = priority
        if key not in self._batches:
            self._batches[key] = []
        self._batches[key].append({"title": title, "message": message, "priority": priority})
        if key not in self._tasks or self._tasks[key].done():
            self._tasks[key] = asyncio.create_task(self._send_batch(key))

    async def _send_batch(self, key: str):
        await asyncio.sleep(self.delay)
        batch = self._batches.pop(key, [])
        for item in batch:
            await notify_notification(title=item["title"], message=item["message"], priority=item["priority"])

    async def flush(self):
        for key in list(self._batches.keys()):
            batch = self._batches.pop(key, [])
            for item in batch:
                await notify_notification(title=item["title"], message=item["message"], priority=item["priority"])


notification_batcher = NotificationBatcher()


async def flush_notification_batches():
    await notification_batcher.flush()
