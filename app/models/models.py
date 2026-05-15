"""
app/models/models.py
VERZIJA: 9.0.0 — Multi-tenant (library_id u svim tablicama)

IZMJENE:
  - Book, Member, Loan, Reservation, Rating — svaki dobiva library_id
  - isbn i member_number više nisu globalno unique — unique po library_id
  - Dodani indeksi na library_id za performanse
"""
from app.database import Base
from sqlalchemy import (Boolean, Column, Date, DateTime, Float, ForeignKey,
                        Integer, String, Text, UniqueConstraint, func)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func


class Book(Base):
    __tablename__ = "books"
    __table_args__ = (
        UniqueConstraint("library_id", "isbn", name="uq_book_library_isbn"),
    )

    id              = Column(Integer, primary_key=True, index=True)
    library_id      = Column(Integer, ForeignKey("biblioteke.id"), nullable=False, index=True)
    isbn            = Column(String,  nullable=True, index=True)
    title           = Column(String,  nullable=False, index=True)
    author          = Column(String,  nullable=False)
    publisher       = Column(String,  nullable=True)
    year            = Column(Integer, nullable=True)
    genre           = Column(String,  nullable=True)
    shelf           = Column(String,  nullable=True)
    language        = Column(String,  nullable=True, default="hr")
    series          = Column(String,  nullable=True)
    series_order    = Column(Integer, nullable=True)
    tags            = Column(String,  nullable=True)
    total_copies    = Column(Integer, default=1)
    available_copies= Column(Integer, default=1)
    description     = Column(Text,    nullable=True)
    cover_url       = Column(String,  nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    loans        = relationship("Loan",        back_populates="book")
    reservations = relationship("Reservation", back_populates="book")
    ratings      = relationship("Rating",      back_populates="book")

    @property
    def average_rating(self):
        if not self.ratings:
            return None
        total = sum(r.rating for r in self.ratings)
        return round(total / len(self.ratings), 1)


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (
        UniqueConstraint("library_id", "member_number", name="uq_member_library_number"),
    )

    id            = Column(Integer, primary_key=True, index=True)
    library_id    = Column(Integer, ForeignKey("biblioteke.id"), nullable=False, index=True)
    member_number = Column(String,  nullable=False, index=True)
    first_name    = Column(String,  nullable=False)
    last_name     = Column(String,  nullable=False)
    email         = Column(String,  nullable=True, index=True)
    phone         = Column(String,  nullable=True)
    address       = Column(String,  nullable=True)
    is_active     = Column(Boolean, default=True)
    joined_date   = Column(Date,    nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    loans        = relationship("Loan",        back_populates="member")
    reservations = relationship("Reservation", back_populates="member")
    ratings      = relationship("Rating",      back_populates="member")


class Loan(Base):
    __tablename__ = "loans"

    id          = Column(Integer, primary_key=True, index=True)
    library_id  = Column(Integer, ForeignKey("biblioteke.id"), nullable=False, index=True)
    book_id     = Column(Integer, ForeignKey("books.id"),    nullable=False)
    member_id   = Column(Integer, ForeignKey("members.id"), nullable=False)
    loan_date   = Column(Date,    nullable=False)
    due_date    = Column(Date,    nullable=False)
    return_date = Column(Date,    nullable=True)
    is_returned = Column(Boolean, default=False)
    notes       = Column(Text,    nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    book   = relationship("Book",   back_populates="loans")
    member = relationship("Member", back_populates="loans")


class Reservation(Base):
    __tablename__ = "reservations"

    id          = Column(Integer, primary_key=True, index=True)
    library_id  = Column(Integer, ForeignKey("biblioteke.id"), nullable=False, index=True)
    book_id     = Column(Integer, ForeignKey("books.id"),    nullable=False)
    member_id   = Column(Integer, ForeignKey("members.id"), nullable=False)
    reserved_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active   = Column(Boolean, default=True)

    book   = relationship("Book",   back_populates="reservations")
    member = relationship("Member", back_populates="reservations")


class Rating(Base):
    __tablename__ = "ratings"

    id         = Column(Integer, primary_key=True, index=True)
    library_id = Column(Integer, ForeignKey("biblioteke.id"), nullable=False, index=True)
    book_id    = Column(Integer, ForeignKey("books.id"),    nullable=False)
    member_id  = Column(Integer, ForeignKey("members.id"), nullable=False)
    rating     = Column(Integer, nullable=False)  # 1-5
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    book   = relationship("Book",   back_populates="ratings")
    member = relationship("Member", back_populates="ratings")
