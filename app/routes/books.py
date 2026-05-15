"""
app/routes/books.py
VERZIJA: 9.1.5 — Ispravak: redoslijed ruta (/genres/list ispred /{book_id}),
    IntegrityError -> 400, Provjera FK knjiznice, azuriranje/brisanje konzistentno s get_library_id
"""
from datetime import datetime
from typing import Any, List, Optional

from app.auth import get_current_user, get_library_id, require_staff
from app.database import get_db
from app.models.library import Library
from app.models.models import Book, Loan, Member, Rating
from app.models.user import User
from app.schemas.schemas import BookCreate, BookOut, BookUpdate, PagedResponse
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

router = APIRouter(prefix="/books", tags=["Knjige"])


def _books_query(db: Session, library_id: Optional[int]):
    """Centralni query za knjige — uvijek filtrira po library_id."""
    q = db.query(Book)
    if library_id is not None:
        q = q.filter(Book.library_id == library_id)
    return q


@router.get("/", response_model=PagedResponse[BookOut])
def get_books(
    skip: int = Query(0, ge=0, description="Broj zapisa koje preskociti"),
    limit: int = Query(50, ge=1, le=200, description="Maks. zapisa po stranici (max 200)"),
    search: Optional[str] = Query(None),
    genre: Optional[str] = None,
    available_only: bool = False,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    query = _books_query(db, library_id)
    if search:
        query = query.filter(or_(
            Book.title.ilike(f"%{search}%"),
            Book.author.ilike(f"%{search}%"),
            Book.isbn == search,
            Book.isbn.ilike(f"%{search}%"),
        ))
    if genre:
        query = query.filter(Book.genre == genre)
    if available_only:
        query = query.filter(Book.available_copies > 0)
    total = query.count()
    items = query.offset(skip).limit(limit).all()
    return PagedResponse.create(items=items, total=total, skip=skip, limit=limit)


@router.get("/isbn/{isbn}", response_model=BookOut)
def get_book_by_isbn(
    isbn: str,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    book = _books_query(db, library_id).filter(Book.isbn == isbn).first()
    if not book:
        raise HTTPException(status_code=404, detail=f"Knjiga s ISBN {isbn} nije pronadjena")
    return book


@router.get("/search/advanced", response_model=PagedResponse[BookOut])
def advanced_search(
    q: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
    author: Optional[str] = Query(None),
    year_from: Optional[int] = Query(None, ge=1800, le=2100),
    year_to: Optional[int] = Query(None, ge=1800, le=2100),
    shelf: Optional[str] = Query(None),
    language: Optional[str] = Query(None),
    series: Optional[str] = Query(None),
    tags: Optional[str] = Query(None),
    available_only: Optional[bool] = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    query = _books_query(db, library_id)
    if q:
        query = query.filter(or_(
            Book.title.ilike(f"%{q}%"),
            Book.author.ilike(f"%{q}%"),
            Book.isbn == q,
        ))
    if genre:      query = query.filter(Book.genre == genre)
    if author:     query = query.filter(Book.author.ilike(f"%{author}%"))
    if year_from:  query = query.filter(Book.year >= year_from)
    if year_to:    query = query.filter(Book.year <= year_to)
    if shelf:      query = query.filter(Book.shelf.ilike(f"%{shelf}%"))
    if language:   query = query.filter(Book.language == language)
    if series:     query = query.filter(Book.series.ilike(f"%{series}%"))
    if tags:       query = query.filter(Book.tags.ilike(f"%{tags}%"))
    if available_only: query = query.filter(Book.available_copies > 0)
    total = query.count()
    items = query.offset(skip).limit(limit).all()
    return PagedResponse.create(items=items, total=total, skip=skip, limit=limit)


# *** FIX v9.1.5: /genres/list MORA biti PRIJE /{book_id} ***
# Inace FastAPI hvata "genres" kao book_id i vraca 422 gresku!
@router.get("/genres/list")
def get_genres(
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    q = db.query(Book.genre).filter(Book.genre.isnot(None))
    if library_id:
        q = q.filter(Book.library_id == library_id)
    genres = q.distinct().all()
    return [g[0] for g in genres if g[0]]


@router.get("/{book_id}", response_model=BookOut)
def get_book(
    book_id: int,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    book = _books_query(db, library_id).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronadjena")
    return book


@router.post("/", response_model=BookOut, status_code=201)
def create_book(
    book: BookCreate,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db),
    library_id: Optional[int] = Query(None, description="library_id za super admina"),
):
    # Odredi u koju knjizicu ici
    if current_user.library_id:
        target_library_id = current_user.library_id  # Normalni admin/knjiznicar
    elif library_id:
        target_library_id = library_id  # Super admin prosljeduje library_id
    else:
        raise HTTPException(
            status_code=400,
            detail="Korisnik nije dodijeljen knjiznici. Super admin mora proslijediti ?library_id=<id>."
        )

    # FIX v9.1.5: Provjeri postoji li knjiznica (FK check) prije db.add()
    lib = db.query(Library).filter(Library.id == target_library_id).first()
    if not lib:
        raise HTTPException(
            status_code=400,
            detail=f"Knjiznica s ID={target_library_id} ne postoji."
        )

    if book.isbn:
        existing = db.query(Book).filter(
            Book.library_id == target_library_id,
            Book.isbn == book.isbn
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Knjiga s ISBN '{book.isbn}' vec postoji u ovoj knjiznici")

    book_data = book.model_dump()
    # available_copies mora odgovarati total_copies pri kreiranju (Bug 2 fix)
    available_copies = book_data.get("total_copies", 1) or 1
    db_book = Book(**book_data, library_id=target_library_id,
                   available_copies=available_copies)
    db.add(db_book)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        # FIX v9.1.5: IntegrityError -> citljiva 400 greska umjesto 500
        raise HTTPException(
            status_code=400,
            detail=f"Greska pri unosu knjige (IntegrityError): {str(e.orig)}"
        )
    db.refresh(db_book)
    return db_book


@router.put("/{book_id}", response_model=BookOut)
def update_book(
    book_id: int,
    book_update: BookUpdate,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db)
):
    # FIX v9.1.5: library_id=None za super admina — moze vidjeti/editirati sve knjige
    lib_id = current_user.library_id
    db_book = _books_query(db, lib_id).filter(Book.id == book_id).first()
    if not db_book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronadjena")

    for field, value in book_update.model_dump(exclude_unset=True).items():
        setattr(db_book, field, value)

    if book_update.total_copies is not None:
        active_loans = db.query(Loan).filter(
            Loan.book_id == book_id,
            Loan.is_returned == False
        ).count()
        db_book.available_copies = max(0, book_update.total_copies - active_loans)

    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Greska pri azuriranju: {str(e.orig)}")
    db.refresh(db_book)
    return db_book


@router.delete("/{book_id}", status_code=204)
def delete_book(
    book_id: int,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db)
):
    # FIX v9.1.5: library_id=None za super admina — moze brisati iz svih knjiznica
    lib_id = current_user.library_id
    db_book = _books_query(db, lib_id).filter(Book.id == book_id).first()
    if not db_book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronadjena")
    db.delete(db_book)
    db.commit()
