from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.sql import func
from app.database import Base


class SyncLog(Base):
    __tablename__ = "sync_log"

    id = Column(Integer, primary_key=True, index=True)
    table_name = Column(String, nullable=False)       # books, members, loans...
    record_id = Column(Integer, nullable=False)
    operation = Column(String, nullable=False)         # INSERT, UPDATE, DELETE
    data = Column(Text, nullable=True)                 # JSON snapshot
    synced = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
