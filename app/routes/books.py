from datetime import datetime
from typing import Any, List, Optional

from app.database import get_db
from app.models.models import Book, Loan, Member, Rating
from app.schemas.schemas import BookCreate, BookOut, BookUpdate
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

router = APIRouter(prefix="/books", tags=["Knjige"])


@router.get("/", response_model=List[BookOut])
def get_books(
    skip: int = 0,
    limit: int = 50,
    search: Optional[str] = Query(None, description="Pretraži po naslovu, autoru ili ISBN-u"),
    genre: Optional[str] = None,
    available_only: bool = False,
    db: Session = Depends(get_db)
):
    """
    Dohvati listu knjiga s opcionalnom pretragom.

    Pretraga (search parametar) pretražuje po:
      - naslovu (LIKE)
      - autoru (LIKE)
      - ISBN-u — exact match ILI LIKE (za skeniranje barkoda)

    ISPRAVAK v8.3: dodan ISBN u WHERE uvjet — ranije je pretraga po ISBN-u
    uvijek vraćala prazan rezultat jer je filtrirala samo naslov i autora.
    """
    query = db.query(Book)
    if search:
        query = query.filter(
            or_(
                Book.title.ilike(f"%{search}%"),
                Book.author.ilike(f"%{search}%"),
                Book.isbn == search,                    # exact ISBN match (skener)
                Book.isbn.ilike(f"%{search}%"),         # partial ISBN match
            )
        )
    if genre:
        query = query.filter(Book.genre == genre)
    if available_only:
        query = query.filter(Book.available_copies > 0)
    return query.offset(skip).limit(limit).all()


@router.get("/isbn/{isbn}", response_model=BookOut)
def get_book_by_isbn(isbn: str, db: Session = Depends(get_db)):
    """
    Dohvati knjigu direktno po ISBN-u (exact match).

    NOVO v8.3: namjenski endpoint za ISBN skeniranje — brži od search
    jer radi exact match bez LIKE upita. Vraća 404 ako knjiga nije u
    knjižnici (korisna poruka za ScanLoanDialog).
    """
    book = db.query(Book).filter(Book.isbn == isbn).first()
    if not book:
        raise HTTPException(
            status_code=404,
            detail=f"Knjiga s ISBN {isbn} nije pronađena u knjižnici"
        )
    return book


@router.get("/search/advanced")
def advanced_search(
    q: Optional[str] = Query(None, description="Pretražni pojam"),
    genre: Optional[str] = Query(None, description="Žanr"),
    author: Optional[str] = Query(None, description="Autor"),
    year_from: Optional[int] = Query(None, ge=1800, le=2100, description="Godina od"),
    year_to: Optional[int] = Query(None, ge=1800, le=2100, description="Godina do"),
    shelf: Optional[str] = Query(None, description="Polica"),
    language: Optional[str] = Query(None, description="Jezik knjige"),
    series: Optional[str] = Query(None, description="Serijal/kolekcija"),
    tags: Optional[str] = Query(None, description="Tagovi"),
    available_only: Optional[bool] = Query(False, description="Samo dostupne"),
    rating_min: Optional[float] = Query(None, ge=0, le=5, description="Minimalna ocjena"),
    sort_by: Optional[str] = Query("title", description="Sortiraj po (title, year, rating, loans, date)"),
    sort_order: Optional[str] = Query("asc", description="Redoslijed (asc, desc)"),
    page: Optional[int] = Query(1, ge=1, description="Stranica"),
    per_page: Optional[int] = Query(20, ge=1, le=100, description="Stavki po stranici"),
    fuzzy: Optional[bool] = Query(False, description="Fuzzy pretraga"),
    db: Session = Depends(get_db)
):
    """
    Napredno pretraživanje knjiga s filtrima i sortiranjem.
    """
    query = db.query(Book)

    # Pretraga po tekstu
    if q:
        if fuzzy:
            search_term = f"%{q}%"
            query = query.filter(
                or_(
                    Book.title.ilike(search_term),
                    Book.author.ilike(search_term),
                    Book.isbn.ilike(search_term),
                    Book.genre.ilike(search_term),
                    Book.description.ilike(search_term)
                )
            )
        else:
            query = query.filter(
                or_(
                    Book.title.ilike(f"%{q}%"),
                    Book.author.ilike(f"%{q}%"),
                    Book.isbn == q
                )
            )

    # Filtri
    if genre:
        query = query.filter(Book.genre.ilike(f"%{genre}%"))
    if author:
        query = query.filter(Book.author.ilike(f"%{author}%"))
    if year_from:
        query = query.filter(Book.year >= year_from)
    if year_to:
        query = query.filter(Book.year <= year_to)
    if shelf:
        query = query.filter(Book.shelf.ilike(f"%{shelf}%"))
    if language:
        query = query.filter(Book.language == language)
    if series:
        query = query.filter(Book.series.ilike(f"%{series}%"))
    if tags:
        query = query.filter(Book.tags.ilike(f"%{tags}%"))
    if available_only:
        query = query.filter(Book.available_copies > 0)

    # Filtriranje po minimalnoj ocjeni
    if rating_min is not None:
        avg_rating_subq = (
            db.query(
                Rating.book_id,
                func.avg(Rating.rating).label('avg_rating')
            )
            .group_by(Rating.book_id)
            .having(func.avg(Rating.rating) >= rating_min)
            .subquery()
        )
        query = query.join(avg_rating_subq, Book.id == avg_rating_subq.c.book_id)

    # Sortiranje
    if sort_by == "title":
        query = query.order_by(Book.title.asc() if sort_order == "asc" else Book.title.desc())
    elif sort_by == "year":
        query = query.order_by(Book.year.asc() if sort_order == "asc" else Book.year.desc())
    elif sort_by == "rating":
        avg_rating_subq = (
            db.query(
                Rating.book_id,
                func.avg(Rating.rating).label('avg_rating')
            )
            .group_by(Rating.book_id)
            .subquery()
        )
        query = query.outerjoin(avg_rating_subq, Book.id == avg_rating_subq.c.book_id).order_by(
            avg_rating_subq.c.avg_rating.asc() if sort_order == "asc" else avg_rating_subq.c.avg_rating.desc().nullslast()
        )
    elif sort_by == "loans":
        loan_count_subq = (
            db.query(
                Loan.book_id,
                func.count(Loan.id).label('loan_count')
            )
            .group_by(Loan.book_id)
            .subquery()
        )
        query = query.outerjoin(loan_count_subq, Book.id == loan_count_subq.c.book_id).order_by(
            loan_count_subq.c.loan_count.asc() if sort_order == "asc" else loan_count_subq.c.loan_count.desc().nullslast()
        )
    elif sort_by == "date":
        query = query.order_by(Book.created_at.asc() if sort_order == "asc" else Book.created_at.desc())

    # Pagination
    offset = (page - 1) * per_page
    total = query.count()
    books = query.offset(offset).limit(per_page).all()

    # Formatiranje rezultata
    result = []
    for book in books:
        ratings = db.query(Rating).filter(Rating.book_id == book.id).all()
        avg_rating = round(sum(r.rating for r in ratings) / len(ratings), 1) if ratings else None
        loan_count = db.query(Loan).filter(Loan.book_id == book.id).count()

        result.append({
            "id": book.id,
            "isbn": book.isbn,
            "title": book.title,
            "author": book.author,
            "publisher": book.publisher,
            "year": book.year,
            "genre": book.genre,
            "shelf": book.shelf,
            "language": book.language,
            "series": book.series,
            "series_order": book.series_order,
            "tags": book.tags,
            "total_copies": book.total_copies,
            "available_copies": book.available_copies,
            "description": book.description,
            "cover_url": book.cover_url,
            "created_at": book.created_at,
            "average_rating": avg_rating,
            "loan_count": loan_count
        })

    return {
        "books": result,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page
    }


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
