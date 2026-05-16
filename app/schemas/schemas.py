from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr

# ── BOOK SCHEMAS ──────────────────────────────────────────────────────────────

class BookBase(BaseModel):
    isbn: Optional[str] = None
    title: str
    author: str
    publisher: Optional[str] = None
    year: Optional[int] = None
    genre: Optional[str] = None
    shelf: Optional[str] = None  # Polica na kojoj se knjiga nalazi
    language: Optional[str] = "hr"  # Jezik knjige
    series: Optional[str] = None  # Serijal/kolekcija
    series_order: Optional[int] = None  # Redni broj u serijalu
    tags: Optional[str] = None  # Tagovi (comma-separated)
    total_copies: int = 1
    description: Optional[str] = None
    cover_url: Optional[str] = None

class BookCreate(BookBase):
    pass

class BookUpdate(BaseModel):
    isbn: Optional[str] = None
    title: Optional[str] = None
    author: Optional[str] = None
    publisher: Optional[str] = None
    year: Optional[int] = None
    genre: Optional[str] = None
    shelf: Optional[str] = None  # Polica na kojoj se knjiga nalazi
    language: Optional[str] = None  # Jezik knjige
    series: Optional[str] = None  # Serijal/kolekcija
    series_order: Optional[int] = None  # Redni broj u serijalu
    tags: Optional[str] = None  # Tagovi (comma-separated)
    total_copies: Optional[int] = None
    description: Optional[str] = None
    cover_url: Optional[str] = None

class BookOut(BookBase):
    id: int
    available_copies: int
    created_at: datetime
    average_rating: Optional[float] = None

    class Config:
        from_attributes = True




class BookSimple(BookBase):
    """BookOut bez average_rating - koristi se u LoanOut/ReservationOut
    da izbjegnemo lazy load gresku na ratings relaciji."""
    id: int
    available_copies: int
    created_at: datetime

    class Config:
        from_attributes = True
# ── MEMBER SCHEMAS ────────────────────────────────────────────────────────────

class MemberBase(BaseModel):
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    joined_date: Optional[date] = None

class MemberCreate(MemberBase):
    pass

class MemberUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    is_active: Optional[bool] = None

class MemberOut(MemberBase):
    id: int
    member_number: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── LOAN SCHEMAS ──────────────────────────────────────────────────────────────

class LoanCreate(BaseModel):
    book_id: int
    member_id: int
    loan_date: date
    due_date: date
    notes: Optional[str] = None

class LoanReturn(BaseModel):
    return_date: Optional[date] = None

class LoanOut(BaseModel):
    id: int
    book_id: int
    member_id: int
    loan_date: date
    due_date: date
    return_date: Optional[date] = None
    is_returned: bool
    notes: Optional[str] = None
    book: Optional[BookSimple] = None
    member: Optional[MemberOut] = None

    class Config:
        from_attributes = True


# ── RESERVATION SCHEMAS ───────────────────────────────────────────────────────

class ReservationCreate(BaseModel):
    book_id: int
    member_id: int

class ReservationOut(BaseModel):
    id: int
    book_id: int
    member_id: int
    reserved_at: datetime
    is_active: bool
    book: BookSimple
    member: MemberOut

    class Config:
        from_attributes = True


# ── RATING SCHEMAS ────────────────────────────────────────────────────────────

class RatingCreate(BaseModel):
    rating: int  # 1-3

class RatingOut(BaseModel):
    id: int
    book_id: int
    member_id: int
    rating: int
    created_at: datetime

    class Config:
        from_attributes = True


# ── PAGINACIJA ────────────────────────────────────────────────────────────────

from typing import TypeVar, Generic
from pydantic import BaseModel as PydanticBase

T = TypeVar("T")

class PagedResponse(PydanticBase, Generic[T]):
    """Standardni paginirani odgovor za sve list endpointe."""
    items: List[T]
    total: int
    skip: int
    limit: int
    has_more: bool

    @classmethod
    def create(cls, items: list, total: int, skip: int, limit: int) -> "PagedResponse":
        return cls(
            items=items,
            total=total,
            skip=skip,
            limit=limit,
            has_more=(skip + len(items)) < total,
        )
