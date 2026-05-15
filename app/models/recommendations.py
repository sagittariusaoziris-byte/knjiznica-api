from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class BookRecommendation(Base):
    """Preporuke knjiga — dodaje knjižničar/admin, vide svi."""
    __tablename__ = "book_recommendations"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    added_by = Column(String, nullable=False)  # username koji je dodao
    note = Column(Text, nullable=True)          # komentar/opis preporuke
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    book = relationship("Book")


class MemberBookmark(Base):
    """Član označava knjigu zvjezdicom (lajk)."""
    __tablename__ = "member_bookmarks"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    book = relationship("Book")
    member = relationship("Member")


class ReservationRequest(Base):
    """Zahtjev za rezervaciju — član šalje, knjižničar obrađuje."""
    __tablename__ = "reservation_requests"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    note = Column(Text, nullable=True)
    status = Column(String, default="pending")  # pending, approved, rejected
    response_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    book = relationship("Book")
    member = relationship("Member")
