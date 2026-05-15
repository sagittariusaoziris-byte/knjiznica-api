"""
Pydantic schemas for notifications.
"""
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict


class NotificationBase(BaseModel):
    """Base schema for notifications."""

    type: str
    priority: str = "medium"
    title: str
    message: str
    data: Optional[Dict[str, Any]] = {}


class NotificationCreate(NotificationBase):
    """Schema for creating a notification."""

    user_id: Optional[int] = None


class NotificationUpdate(BaseModel):
    """Schema for updating a notification."""

    is_read: Optional[bool] = None
    priority: Optional[str] = None


class NotificationOut(NotificationBase):
    """Schema for notification output."""

    id: int
    is_read: bool
    created_at: datetime
    user_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

    @property
    def icon(self) -> str:
        """Get icon for notification type."""
        icons = {
            "loan_created": "📚",
            "book_returned": "✅",
            "overdue": "⚠️",
            "reservation_ready": "📖",
            "reservation_created": "📝",
            "member_blocked": "🚫",
            "system": "ℹ️",
            "error": "❌",
            "success": "🎉",
        }
        return icons.get(self.type, "🔔")

    @property
    def color(self) -> str:
        """Get color for priority level."""
        colors = {
            "low": "#6c757d",
            "medium": "#17a2b8",
            "high": "#fd7e14",
            "urgent": "#dc3545",
        }
        return colors.get(self.priority, "#6c757d")


class NotificationStats(BaseModel):
    """Schema for notification statistics."""

    total: int
    unread: int
    by_type: Dict[str, int]
    by_priority: Dict[str, int]
