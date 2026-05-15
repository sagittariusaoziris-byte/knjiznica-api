"""
app/routes/books.py
VERZIJA: 9.1.5 — Ispravak: redoslijed ruta (/genres/list ispred /{book_id}),
    IntegrityError -> 400, FK provjera knjiznice, average_rating SQL subquery (bez lazy load)
"""
from typing import Optional

from app.auth import get_library_id, require_staff
from app.database import get_db
from app.models.library import Library
from app.models.models import Book, Loan, Rating
from app.models.user import User
from app.schemas.schemas import BookCreate, BookOut, BookUpdate, PagedResponse
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

router = APIRouter(prefix="/books", tags=["Knjige"])


def _books_query(db: Session, library_id: Optional[int]):
    """Centralni query za knjige - uvijek filtrira po library_id."""
    q = db.query(Book)
    if library_id is not None:
        q = q.filter(Book.library_id == library_id)
    return q


def _get_avg_map(db: Session, book_ids: list) -> dict:
    """Dohvati average_rating za listu book_ids direktno SQL-om (bez lazy load)."""
    if not book_ids:
        return {}
    rows = (
        db.query(Rating.book_id, func.avg(Rating.rating).label("avg"))
        .filter(Rating.book_id.in_(book_ids))
        .group_by(Rating.book_id)
        .all()
    )
    return {r.book_id: round(float(r.avg), 1) for r in rows}


def _to_book_out(book: Book, avg_map: dict) -> BookOut:
    """Konvertira Book ORM objekt u BookOut bez lazy load relacija."""
    return BookOut(
        id=book.id,
        isbn=book.isbn,
        title=book.title,
        author=book.author,
        publisher=book.publisher,
        year=book.year,
        genre=book.genre,
        shelf=book.shelf,
        language=book.language,
        series=book.series,
        series_order=book.series_order,
        tags=book.tags,
        total_copies=book.total_copies,
        available_copies=book.available_copies,
        description=book.description,
        cover_url=book.cover_url,
        created_at=book.created_at,
        average_rating=avg_map.get(book.id),
    )


@router.get("/", response_model=PagedResponse[BookOut])
def get_books(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
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
    books = query.offset(skip).limit(limit).all()
    avg_map = _get_avg_map(db, [b.id for b in books])
    items = [_to_book_out(b, avg_map) for b in books]
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
    return _to_book_out(book, _get_avg_map(db, [book.id]))


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
    books = query.offset(skip).limit(limit).all()
    avg_map = _get_avg_map(db, [b.id for b in books])
    items = [_to_book_out(b, avg_map) for b in books]
    return PagedResponse.create(items=items, total=total, skip=skip, limit=limit)


# *** FIX v9.1.5: /genres/list MORA biti PRIJE /{book_id} ***
@router.get("/genres/list")
def get_genres(
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    q = db.query(Book.genre).filter(Book.genre.isnot(None))
    if library_id:
        q = q.filter(Book.library_id == library_id)
    return [g[0] for g in q.distinct().all() if g[0]]


@router.get("/{book_id}", response_model=BookOut)
def get_book(
    book_id: int,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    book = _books_query(db, library_id).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronadjena")
    return _to_book_out(book, _get_avg_map(db, [book.id]))


@router.post("/", response_model=BookOut, status_code=201)
def create_book(
    book: BookCreate,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db),
    library_id: Optional[int] = Query(None, description="library_id za super admina"),
):
    if current_user.library_id:
        target_library_id = current_user.library_id
    elif library_id:
        target_library_id = library_id
    else:
        raise HTTPException(status_code=400,
            detail="Korisnik nije dodijeljen knjiznici. Super admin mora proslijediti ?library_id=<id>.")

    lib = db.query(Library).filter(Library.id == target_library_id).first()
    if not lib:
        raise HTTPException(status_code=400, detail=f"Knjiznica s ID={target_library_id} ne postoji.")

    if book.isbn:
        existing = db.query(Book).filter(
            Book.library_id == target_library_id,
            Book.isbn == book.isbn
        ).first()
        if existing:
            raise HTTPException(status_code=400,
                detail=f"Knjiga s ISBN '{book.isbn}' vec postoji u ovoj knjiznici")

    book_data = book.model_dump()
    available_copies = book_data.get("total_copies", 1) or 1
    db_book = Book(**book_data, library_id=target_library_id, available_copies=available_copies)
    db.add(db_book)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Greska pri unosu knjige: {str(e.orig)}")
    db.refresh(db_book)
    return _to_book_out(db_book, {})


@router.put("/{book_id}", response_model=BookOut)
def update_book(
    book_id: int,
    book_update: BookUpdate,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db)
):
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
    return _to_book_out(db_book, _get_avg_map(db, [book_id]))


@router.delete("/{book_id}", status_code=204)
def delete_book(
    book_id: int,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db)
):
    lib_id = current_user.library_id
    db_book = _books_query(db, lib_id).filter(Book.id == book_id).first()
    if not db_book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronadjena")
    db.delete(db_book)
    db.commit()
