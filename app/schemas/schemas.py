from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import date, datetime


# ── BOOK SCHEMAS ──────────────────────────────────────────────────────────────

class BookBase(BaseModel):
    isbn: Optional[str] = None
    title: str
    author: str
    publisher: Optional[str] = None
    year: Optional[int] = None
    genre: Optional[str] = None
    total_copies: int = 1
    description: Optional[str] = None

class BookCreate(BookBase):
    pass

class BookUpdate(BaseModel):
    isbn: Optional[str] = None
    title: Optional[str] = None
    author: Optional[str] = None
    publisher: Optional[str] = None
    year: Optional[int] = None
    genre: Optional[str] = None
    total_copies: Optional[int] = None
    description: Optional[str] = None

class BookOut(BookBase):
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
    return_date: date

class LoanOut(BaseModel):
    id: int
    book_id: int
    member_id: int
    loan_date: date
    due_date: date
    return_date: Optional[date] = None
    is_returned: bool
    notes: Optional[str] = None
    book: BookOut
    member: MemberOut

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
    book: BookOut
    member: MemberOut

    class Config:
        from_attributes = True
