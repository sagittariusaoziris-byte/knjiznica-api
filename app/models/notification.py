"""
app/models/notification.py
VERZIJA: 9.0.0 — library_id dodан
"""
from datetime import datetime
from app.database import Base
from sqlalchemy import (JSON, Boolean, Column, DateTime, ForeignKey, Integer, String)
from sqlalchemy.orm import relationship


class Notification(Base):
    __tablename__ = "notifications"

    id         = Column(Integer, primary_key=True, index=True)
    library_id = Column(Integer, ForeignKey("libraries.id"), nullable=True, index=True)
    type       = Column(String,  nullable=False)
    priority   = Column(String,  default="medium")
    title      = Column(String,  nullable=False)
    message    = Column(String,  nullable=False)
    data       = Column(JSON,    default={})
    is_read    = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=True)

    user = relationship("User", back_populates="notifications")
