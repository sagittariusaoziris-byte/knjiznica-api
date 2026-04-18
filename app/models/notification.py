"""
Notification model for storing notification history.
"""
from datetime import datetime
from typing import Optional

from app.database import Base
from sqlalchemy import (JSON, Boolean, Column, DateTime, ForeignKey, Integer,
                        String)
from sqlalchemy.orm import relationship


class Notification(Base):
    """Model za pohranu obavijesti."""

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, nullable=False)  # loan_created, book_returned, overdue, etc.
    priority = Column(String, default="medium")  # low, medium, high, urgent
    title = Column(String, nullable=False)
    message = Column(String, nullable=False)
    data = Column(JSON, default={})  # Dodatni podaci u JSON formatu
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # Kome je namijenjena

    # Relationships
    user = relationship("User", back_populates="notifications")

    def __repr__(self):
        return f"<Notification(id={self.id}, type='{self.type}', priority='{self.priority}')>"

    def to_dict(self):
        """Convert notification to dictionary."""
        return {
            "id": self.id,
            "type": self.type,
            "priority": self.priority,
            "title": self.title,
            "message": self.message,
            "data": self.data,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "user_id": self.user_id,
        }

    @staticmethod
    def get_type_icon(notification_type: str) -> str:
        """Returns icon for notification type."""
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
        return icons.get(notification_type, "🔔")

    @staticmethod
    def get_priority_color(priority: str) -> str:
        """Returns color for priority level."""
        colors = {
            "low": "#6c757d",
            "medium": "#17a2b8",
            "high": "#fd7e14",
            "urgent": "#dc3545",
        }
        return colors.get(priority, "#6c757d")
