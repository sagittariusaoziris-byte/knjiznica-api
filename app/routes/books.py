from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models.models import Book
from app.schemas.schemas import BookCreate, BookUpdate, BookOut

router = APIRouter(prefix="/books", tags=["Knjige"])


@router.get("/", response_model=List[BookOut])
def get_books(
    skip: int = 0,
    limit: int = 50,
    search: Optional[str] = Query(None, description="Pretraži po naslovu ili autoru"),
    genre: Optional[str] = None,
    available_only: bool = False,
    db: Session = Depends(get_db)
):
    query = db.query(Book)
    if search:
        query = query.filter(
            (Book.title.ilike(f"%{search}%")) | (Book.author.ilike(f"%{search}%"))
        )
    if genre:
        query = query.filter(Book.genre == genre)
    if available_only:
        query = query.filter(Book.available_copies > 0)
    return query.offset(skip).limit(limit).all()


@router.get("/{book_id}", response_model=BookOut)
def get_book(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")
    return book


@router.post("/", response_model=BookOut, status_code=201)
def create_book(book: BookCreate, db: Session = Depends(get_db)):
    if book.isbn:
        existing = db.query(Book).filter(Book.isbn == book.isbn).first()
        if existing:
            raise HTTPException(status_code=400, detail="Knjiga s tim ISBN-om već postoji")
    db_book = Book(**book.model_dump(), available_copies=book.total_copies)
    db.add(db_book)
    db.commit()
    db.refresh(db_book)
    return db_book


@router.put("/{book_id}", response_model=BookOut)
def update_book(book_id: int, book: BookUpdate, db: Session = Depends(get_db)):
    db_book = db.query(Book).filter(Book.id == book_id).first()
    if not db_book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")
    update_data = book.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_book, key, value)
    db.commit()
    db.refresh(db_book)
    return db_book


@router.delete("/{book_id}", status_code=204)
def delete_book(book_id: int, db: Session = Depends(get_db)):
    db_book = db.query(Book).filter(Book.id == book_id).first()
    if not db_book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")
    db.delete(db_book)
    db.commit()
