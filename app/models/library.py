"""
app/models/library.py
Model za knjižnice (multi-tenant Opcija A)

Svaka knjižnica je tenant — ima library_id koji se propagira
kroz sve tablice (books, members, loans, reservations, notifications,
recommendations, ratings).

VERZIJA: 9.0.0 — Multi-tenant (library_id)
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class Library(Base):
    """Tablica knjižnica — master lista tenanata."""
    __tablename__ = "libraries"

    id           = Column(Integer, primary_key=True, index=True)
    name         = Column(String(128), nullable=False)           # "Knjižnica Bugojno"
    slug         = Column(String(64),  nullable=False, unique=True)  # "bugojno"
    city         = Column(String(64),  nullable=True)
    address      = Column(String(255), nullable=True)
    email        = Column(String(128), nullable=True)
    phone        = Column(String(32),  nullable=True)
    is_active    = Column(Boolean,     default=True, nullable=False)
    notes        = Column(Text,        nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<Library id={self.id} slug={self.slug}>"
