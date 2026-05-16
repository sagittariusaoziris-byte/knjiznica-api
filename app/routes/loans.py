"""
app/routes/loans.py
VERZIJA: 9.1.4 — Paginacija (PagedResponse) na list endpointu
"""
import asyncio
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_library_id, require_staff
from app.database import get_db
from app.models.models import Book, Loan, Member
from app.models.user import User
from app.schemas.schemas import LoanCreate, LoanOut, LoanReturn, PagedResponse
from app.websocket import (NotificationTypes, manager, notify_data_update,
                           notify_loan_status)

router = APIRouter(prefix="/loans", tags=["Posudbe"])

@router.get("/debug/list")
def debug_loans_list(db: Session = Depends(get_db)):
    """Debug - bez auth, hvata tocnu gresku"""
    import traceback
    try:
        from sqlalchemy.orm import joinedload
        items = db.query(Loan).options(
            joinedload(Loan.book),
            joinedload(Loan.member)
        ).filter(Loan.library_id == 1).limit(3).all()
        result = []
        for loan in items:
            try:
                from app.schemas.schemas import LoanOut
                d = LoanOut.model_validate(loan)
                result.append({"id": loan.id, "ok": True})
            except Exception as e:
                result.append({"id": loan.id, "error": str(e), "trace": traceback.format_exc()})
        return {"count": len(result), "items": result}
    except Exception as e:
        return {"ok": False, "error": str(e), "trace": traceback.format_exc()}


def _loans_query(db: Session, library_id: Optional[int]):
    q = db.query(Loan)
    if library_id is not None:
        q = q.filter(Loan.library_id == library_id)
    return q


@router.get("/", response_model=PagedResponse[LoanOut])
def get_loans(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    member_id: Optional[int] = None,
    book_id: Optional[int] = None,
    active_only: bool = False,
    overdue_only: bool = False,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    query = _loans_query(db, library_id)
    if member_id:    query = query.filter(Loan.member_id == member_id)
    if book_id:      query = query.filter(Loan.book_id == book_id)
    if active_only:  query = query.filter(Loan.is_returned == False)
    if overdue_only: query = query.filter(Loan.is_returned == False, Loan.due_date < date.today())
    total = query.count()
    from sqlalchemy.orm import joinedload
    items = query.options(
        joinedload(Loan.book).joinedload(Book.ratings),
        joinedload(Loan.member)
    ).offset(skip).limit(limit).all()
    return PagedResponse.create(items=items, total=total, skip=skip, limit=limit)


@router.get("/{loan_id}", response_model=LoanOut)
def get_loan(
    loan_id: int,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    from sqlalchemy.orm import joinedload
    loan = _loans_query(db, library_id).options(
        joinedload(Loan.book).joinedload(Book.ratings),
        joinedload(Loan.member)
    ).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Posudba nije pronađena")
    return loan


@router.post("/", response_model=LoanOut, status_code=201)
async def create_loan(
    loan: LoanCreate,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db)
):
    if not current_user.library_id:
        raise HTTPException(status_code=400, detail="Korisnik nije dodijeljen knjižnici")

    lib_id = current_user.library_id

    book = db.query(Book).filter(Book.id == loan.book_id, Book.library_id == lib_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")
    if book.available_copies < 1:
        raise HTTPException(status_code=400, detail="Nema dostupnih primjeraka")

    member = db.query(Member).filter(Member.id == loan.member_id, Member.library_id == lib_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Član nije pronađen")
    if not member.is_active:
        raise HTTPException(status_code=400, detail="Član nije aktivan")

    db_loan = Loan(**loan.model_dump(), library_id=lib_id)
    db.add(db_loan)
    book.available_copies -= 1
    db.commit()
    db.refresh(db_loan)

    asyncio.create_task(notify_data_update("loan", "created", {"loan_id": db_loan.id}))
    return db_loan


@router.post("/{loan_id}/return", response_model=LoanOut)
async def return_loan(
    loan_id: int,
    data: LoanReturn,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db)
):
    loan = _loans_query(db, current_user.library_id).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Posudba nije pronađena")
    if loan.is_returned:
        raise HTTPException(status_code=400, detail="Knjiga je već vraćena")

    loan.is_returned = True
    loan.return_date = data.return_date or date.today()
    if data.notes:
        loan.notes = data.notes

    book = db.query(Book).filter(Book.id == loan.book_id).first()
    if book:
        book.available_copies += 1

    db.commit()
    asyncio.create_task(notify_data_update("loan", "returned", {"loan_id": loan_id}))
    # FIX: vraćamo samo potvrdu umjesto cijelog LoanOut (izbjegava lazy load 500)
    return {"id": loan_id, "is_returned": True}


@router.delete("/{loan_id}", status_code=204)
def delete_loan(
    loan_id: int,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db)
):
    loan = _loans_query(db, current_user.library_id).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Posudba nije pronađena")
    # BUG-FIX: vrati primjerak knjige ako posudba nije vraćena
    if not loan.is_returned:
        book = db.query(Book).filter(Book.id == loan.book_id).first()
        if book:
            book.available_copies += 1
    db.delete(loan)
    db.commit()
