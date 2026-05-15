"""
Pydantic schemas for online users.
"""

import time
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class OnlineUserOut(BaseModel):
    """Schema for online user response."""

    user_id: int
    username: str
    full_name: Optional[str] = None
    role: str
    client_type: str
    connected_at: datetime
    last_seen: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class OnlineUsersResponse(BaseModel):
    """Schema for list of online users."""

    online_users: list[OnlineUserOut]
    total: int
    timestamp: datetime
