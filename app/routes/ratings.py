from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.auth import get_current_user
from app.models.models import Rating, Book, Member
from app.models.user import User
from app.schemas.schemas import RatingCreate, RatingOut

router = APIRouter(prefix="/ratings", tags=["Ocjene"])


@router.post("/{book_id}", status_code=201)
async def rate_book(
    book_id: int,
    data: RatingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Dodaj ili ažuriraj ocjenu knjige"""
    # Validiraj da je ocjena između 1 i 3
    if not (1 <= data.rating <= 3):
        raise HTTPException(status_code=400, detail="Ocjena mora biti između 1 i 3")
    
    # Provjeri da knjiga postoji
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")
    
    # Provjeri da je član prijavljen
    if not current_user.member_id:
        raise HTTPException(status_code=404, detail="Član nije prijavljen")
    
    # Provjeri postoji li već ocjena
    existing_rating = db.query(Rating).filter(
        Rating.book_id == book_id,
        Rating.member_id == current_user.member_id
    ).first()
    
    if existing_rating:
        existing_rating.rating = data.rating
        db.commit()
        db.refresh(existing_rating)
        return existing_rating
    
    # Kreiraj novu ocjenu
    rating = Rating(
        book_id=book_id,
        member_id=current_user.member_id,
        rating=data.rating
    )
    db.add(rating)
    db.commit()
    db.refresh(rating)
    return rating


@router.get("/{book_id}", response_model=dict)
async def get_book_ratings(
    book_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Dohvati sve ocjene za knjizu i prosječnu ocjenu"""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")
    
    ratings = db.query(Rating).filter(Rating.book_id == book_id).all()
    
    if not ratings:
        return {
            "book_id": book_id,
            "average_rating": None,
            "total_ratings": 0,
            "ratings": []
        }
    
    average = sum(r.rating for r in ratings) / len(ratings)
    
    return {
        "book_id": book_id,
        "average_rating": round(average, 1),
        "total_ratings": len(ratings),
        "ratings": [{"member_id": r.member_id, "rating": r.rating} for r in ratings]
    }


@router.get("/member/{member_id}", response_model=List[RatingOut])
async def get_member_ratings(
    member_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user)
):
    """Dohvati sve ocjene koje je dao član"""
    ratings = db.query(Rating).filter(Rating.member_id == member_id).all()
    return ratings


@router.delete("/{book_id}", status_code=204)
async def delete_rating(
    book_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obriši ocjenu koju je dao trenutni korisnik"""
    if not current_user.member_id:
        raise HTTPException(status_code=404, detail="Član nije prijavljen")
    
    rating = db.query(Rating).filter(
        Rating.book_id == book_id,
        Rating.member_id == current_user.member_id
    ).first()
    
    if not rating:
        raise HTTPException(status_code=404, detail="Ocjena nije pronađena")
    
    db.delete(rating)
    db.commit()
