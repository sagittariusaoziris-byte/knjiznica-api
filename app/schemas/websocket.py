from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, validator


class PriorityLevel(str):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class WSMessage(BaseModel):
    """Standard WebSocket message envelope v1.0"""

    version: str = Field("1.0", description="Protocol version")
    type: str  # ping, pong, active_users, chat_message, error, etc.
    client_id: str
    timestamp: str  # ISO format
    priority: Optional[str] = Field(None)
    payload: Optional[Dict[str, Any]] = Field({})
    error_code: Optional[str] = Field(None, description="For error messages")

    @validator("timestamp")
    def validate_timestamp(cls, v):
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
            return v
        except ValueError:
            raise ValueError("Invalid ISO timestamp")


# Specific payloads (nested in envelope.payload)
class PingPayload(BaseModel):
    pass


class PongPayload(BaseModel):
    pass


class ActiveUsersPayload(BaseModel):
    online_users: list[dict]  # [{user_id, username, role, client_type, ...}]
    timestamp: Optional[str] = None


class ChatMessagePayload(BaseModel):
    sender: str
    text: str
    room_id: Optional[str] = None


class ErrorPayload(BaseModel):
    code: str  # INVALID_JSON, INVALID_TYPE, RATE_LIMITED
    message: str
    details: Optional[Dict[str, Any]] = {}


class StatsPayload(BaseModel):
    connections: int
    online_users: int
    online_users_list: list[dict]


# Type registry for easy validation
MESSAGE_TYPES = {
    "ping": PingPayload,
    "pong": PongPayload,
    "active_users": ActiveUsersPayload,
    "chat_message": ChatMessagePayload,
    "error": ErrorPayload,
    "get_online_users": PingPayload,  # Request is simple
    "get_stats": PingPayload,
}


def create_envelope(
    msg_type: str,
    payload: Dict[str, Any] = None,
    client_id: str = "",
    priority: str = None,
    error_code: str = None,
) -> WSMessage:
    """Factory za kreiranje standardnih poruka."""
    return WSMessage(
        type=msg_type,
        client_id=client_id,
        timestamp=datetime.now().isoformat(),
        priority=priority,
        payload=payload or {},
        error_code=error_code,
    )


def parse_message(data: Dict[str, Any]) -> WSMessage:
    """Parse i validate raw dict -> WSMessage."""
    msg = WSMessage(**data)

    # Optional: Validate payload schema by type
    payload_type = MESSAGE_TYPES.get(msg.type)
    if payload_type:
        payload_type(**msg.payload)

    return msg


# Export for router/manager use
__all__ = ["WSMessage", "create_envelope", "parse_message", "MESSAGE_TYPES"]
