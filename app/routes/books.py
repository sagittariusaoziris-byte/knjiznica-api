"""
app/routes/books.py
VERZIJA: 9.2.0 — Fix: delete_book FK zaštita + cascade brisanje zavisnih zapisa
"""
from typing import List, Optional

from app.auth import get_current_user, get_library_id, require_staff
from app.database import get_db
from app.models.library import Library
from app.models.models import Book, Loan, Member, Rating, Reservation
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
    # FIX: eager load ratings da izbjegnemo lazy load 500
    from sqlalchemy.orm import joinedload
    items = query.options(joinedload(Book.ratings)).offset(skip).limit(limit).all()
    return PagedResponse.create(items=items, total=total, skip=skip, limit=limit)


@router.get("/isbn/{isbn}", response_model=BookOut)
def get_book_by_isbn(
    isbn: str,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    book = _books_query(db, library_id).filter(Book.isbn == isbn).first()
    if not book:
        raise HTTPException(status_code=404, detail=f"Knjiga s ISBN {isbn} nije pronadena")
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
    # FIX: eager load ratings da izbjegnemo lazy load 500
    from sqlalchemy.orm import joinedload
    items = query.options(joinedload(Book.ratings)).offset(skip).limit(limit).all()
    return PagedResponse.create(items=items, total=total, skip=skip, limit=limit)


# FIX Bug1: /genres/list MORA biti registriran PRIJE /{book_id}
# FastAPI obradjuje rute redom registracije — /{book_id} bi uhvatio
# /genres/list i pokusao parsirati "genres" kao int -> 422 greska.
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
        raise HTTPException(status_code=404, detail="Knjiga nije pronadena")
    return book


@router.post("/", response_model=BookOut, status_code=201)
def create_book(
    book: BookCreate,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db),
    library_id: Optional[int] = Query(None, description="library_id za super admina"),
):
    # Odredi u koju knjižnicu ici
    if current_user.library_id:
        target_library_id = current_user.library_id  # Normalni admin/knjiznicar
    elif library_id:
        target_library_id = library_id  # Super admin prosljedjuje library_id
    else:
        raise HTTPException(
            status_code=400,
            detail="Korisnik nije dodijeljen knjiznici. Super admin mora proslijediti ?library_id=<id>."
        )

    # FIX v9.1.5: Provjeri postoji li target knjiznica PRIJE db.add()
    # Bez ove provjere, SQLAlchemy baci IntegrityError (FK violation) -> 500
    lib = db.query(Library).filter(Library.id == target_library_id).first()
    if not lib:
        raise HTTPException(
            status_code=400,
            detail=f"Knjiznica s ID={target_library_id} ne postoji. "
                   f"Provjerite library_id korisnika u bazi."
        )

    if book.isbn:
        existing = db.query(Book).filter(
            Book.library_id == target_library_id,
            Book.isbn == book.isbn
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Knjiga s ISBN '{book.isbn}' vec postoji u ovoj knjiznici"
            )

    book_data = book.model_dump()
    available_copies = book_data.get("total_copies", 1) or 1

    # FIX v9.1.5: try/except IntegrityError -> 400 umjesto 500
    try:
        db_book = Book(**book_data, library_id=target_library_id,
                       available_copies=available_copies)
        db.add(db_book)
        db.commit()
        db.refresh(db_book)
        return db_book
    except IntegrityError as e:
        db.rollback()
        detail = str(e.orig) if e.orig else str(e)
        raise HTTPException(status_code=400, detail=f"Greška pri unosu knjige: {detail}")


@router.put("/{book_id}", response_model=BookOut)
def update_book(
    book_id: int,
    book_update: BookUpdate,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db),
    # FIX v9.1.5: current_user.library_id je None za super admina;
    # koristimo get_library_id koji je konzistentan s GET rutama
    library_id: Optional[int] = Depends(get_library_id),
):
    db_book = _books_query(db, library_id).filter(Book.id == book_id).first()
    if not db_book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronadena")

    for field, value in book_update.model_dump(exclude_unset=True).items():
        setattr(db_book, field, value)

    if book_update.total_copies is not None:
        active_loans = db.query(Loan).filter(
            Loan.book_id == book_id,
            Loan.is_returned == False
        ).count()
        db_book.available_copies = max(0, book_update.total_copies - active_loans)

    db.commit()
    db.refresh(db_book)
    return db_book


@router.delete("/{book_id}", status_code=204)
def delete_book(
    book_id: int,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db),
    # FIX v9.1.5: konzistentno s update_book i GET rutama
    library_id: Optional[int] = Depends(get_library_id),
):
    db_book = _books_query(db, library_id).filter(Book.id == book_id).first()
    if not db_book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")
    # BUG-FIX: kaskadno briši zavisne zapise prije brisanja knjige
    active_loans = db.query(Loan).filter(
        Loan.book_id == book_id, Loan.is_returned == False
    ).count()
    if active_loans > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Ne možete obrisati knjigu koja ima {active_loans} aktivnih posudbi."
        )
    # Briši zavisne zapise
    db.query(Rating).filter(Rating.book_id == book_id).delete()
    db.query(Loan).filter(Loan.book_id == book_id).delete()
    db.query(Reservation).filter(Reservation.book_id == book_id).delete()
    try:
        db.delete(db_book)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Knjiga se ne može obrisati jer postoje zavisni zapisi.")
