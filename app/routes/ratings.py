"""
app/routes/ratings.py
VERZIJA: 9.1.0

ISPRAVCI:
  - BookRating model premješten u app/models/book_rating.py (nije smio biti u routes)
  - Ovaj file sada samo importira model i definira rute
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_library_id
from app.database import get_db
from app.models.book_rating import BookRating
from app.models.models import Book
from app.models.user import User

router = APIRouter(prefix="/ratings", tags=["Ocjene"])

# Re-export za backward compat (main.py ga importira za kreiranje tablice)
__all__ = ["router", "BookRating"]


class RatingCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5)


class RatingOut(BaseModel):
    id: int
    book_id: int
    user_id: int
    library_id: Optional[int] = None
    rating: int
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/{book_id}", response_model=List[RatingOut])
def get_ratings(
    book_id: int,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db),
):
    q = db.query(BookRating).filter(BookRating.book_id == book_id)
    if library_id is not None:
        q = q.filter(BookRating.library_id == library_id)
    return q.all()


@router.post("/{book_id}", response_model=RatingOut)
def create_or_update_rating(
    book_id: int,
    data: RatingCreate,
    current_user: User = Depends(get_current_user),
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db),
):
    # Provjeri da knjiga pripada knjižnici
    bq = db.query(Book).filter(Book.id == book_id)
    if library_id is not None:
        bq = bq.filter(Book.library_id == library_id)
    if not bq.first():
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

    rating = BookRating(
        book_id=book_id,
        user_id=current_user.id,
        library_id=library_id,
        rating=data.rating,
    )
    db.add(rating)
    db.commit()
    db.refresh(rating)
    return rating


@router.delete("/{book_id}", status_code=204)
def delete_rating(
    book_id: int,
    current_user: User = Depends(get_current_user),
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db),
):
    rating = db.query(BookRating).filter(
        BookRating.book_id == book_id,
        BookRating.user_id == current_user.id,
    ).first()
    if not rating:
        raise HTTPException(status_code=404, detail="Ocjena nije pronađena")
    db.delete(rating)
    db.commit()
