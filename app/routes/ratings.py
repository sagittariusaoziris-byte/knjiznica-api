"""
app/routes/ratings.py
Ruta za ocjenjivanje knjiga (Ratings) — NOVA DATOTEKA

PROBLEM koji ovo rješava:
  Flutter poziva /ratings/{bookId} (GET, POST, DELETE)
  ali ta ruta NIJE bila registrirana u main.py → 404/500 greška.

Ovaj fajl treba dodati u app/routes/ i registrirati u app/main.py:
  from app.routes import ratings as ratings_router
  app.include_router(ratings_router.router)
"""

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.auth import get_current_user
from app.database import Base, get_db
from app.models.models import Book
from app.models.user import User

router = APIRouter(prefix="/ratings", tags=["Ocjene"])


# ── Model ─────────────────────────────────────────────────────────────────────

class BookRating(Base):
    __tablename__ = "book_ratings"
    __table_args__ = (UniqueConstraint("book_id", "user_id", name="uq_book_user_rating"),)

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ── Schemas ────────────────────────────────────────────────────────────────────

class RatingCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="Ocjena od 1 do 5")


class RatingOut(BaseModel):
    id: int
    book_id: int
    user_id: int
    rating: int
    created_at: datetime

    class Config:
        from_attributes = True


class BookRatingSummary(BaseModel):
    book_id: int
    average_rating: float
    total_ratings: int
    user_rating: Optional[int] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{book_id}", response_model=BookRatingSummary)
async def get_book_ratings(
    book_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dohvati prosječnu ocjenu knjige i ocjenu trenutnog korisnika."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")

    ratings = db.query(BookRating).filter(BookRating.book_id == book_id).all()
    total = len(ratings)
    average = round(sum(r.rating for r in ratings) / total, 2) if total > 0 else 0.0

    user_rating_obj = next((r for r in ratings if r.user_id == current_user.id), None)

    return BookRatingSummary(
        book_id=book_id,
        average_rating=average,
        total_ratings=total,
        user_rating=user_rating_obj.rating if user_rating_obj else None,
    )


@router.post("/{book_id}", response_model=RatingOut, status_code=201)
async def rate_book(
    book_id: int,
    data: RatingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dodaj ili ažuriraj ocjenu knjige (upsert)."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")

    existing = db.query(BookRating).filter(
        BookRating.book_id == book_id,
        BookRating.user_id == current_user.id,
    ).first()

    if existing:
        existing.rating = data.rating
        db.commit()
        db.refresh(existing)
        return existing
    else:
        rating = BookRating(
            book_id=book_id,
            user_id=current_user.id,
            rating=data.rating,
        )
        db.add(rating)
        db.commit()
        db.refresh(rating)
        return rating


@router.delete("/{book_id}", status_code=204)
async def delete_rating(
    book_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Obriši ocjenu trenutnog korisnika za određenu knjigu."""
    rating = db.query(BookRating).filter(
        BookRating.book_id == book_id,
        BookRating.user_id == current_user.id,
    ).first()
    if not rating:
        raise HTTPException(status_code=404, detail="Ocjena nije pronađena")
    db.delete(rating)
    db.commit()
