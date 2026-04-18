import asyncio
from datetime import date
from typing import List, Optional

from app.database import get_db
from app.models.models import Book, Loan, Member
from app.schemas.schemas import LoanCreate, LoanOut, LoanReturn
from app.websocket import (NotificationTypes, manager, notify_data_update,
                           notify_loan_status)
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

router = APIRouter(prefix="/loans", tags=["Posudbe"])


@router.get("/", response_model=List[LoanOut])
def get_loans(
    skip: int = 0,
    limit: int = 50,
    member_id: Optional[int] = None,
    book_id: Optional[int] = None,
    active_only: bool = False,
    overdue_only: bool = False,
    db: Session = Depends(get_db)
):
    query = db.query(Loan)
    if member_id:
        query = query.filter(Loan.member_id == member_id)
    if book_id:
        query = query.filter(Loan.book_id == book_id)
    if active_only:
        query = query.filter(Loan.is_returned == False)
    if overdue_only:
        query = query.filter(Loan.is_returned == False, Loan.due_date < date.today())
    return query.offset(skip).limit(limit).all()


@router.get("/{loan_id}", response_model=LoanOut)
def get_loan(loan_id: int, db: Session = Depends(get_db)):
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Posudba nije pronađena")
    return loan


@router.post("/", response_model=LoanOut, status_code=201)
async def create_loan(loan: LoanCreate, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == loan.book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")
    if book.available_copies < 1:
        raise HTTPException(status_code=400, detail="Nema dostupnih primjeraka")

    member = db.query(Member).filter(Member.id == loan.member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Član nije pronađen")
    if not member.is_active:
        raise HTTPException(status_code=400, detail="Član nije aktivan")

    db_loan = Loan(**loan.model_dump())
    book.available_copies -= 1
    db.add(db_loan)
    db.commit()
    db.refresh(db_loan)

    # ── WebSocket obavijesti (FAZA 1 & 2) ──────────────────────────────────
    # 1. Obavijest o novoj posudbi
    await manager.broadcast({
        "type": NotificationTypes.LOAN_CREATED,
        "loan_id": db_loan.id,
        "book_id": book.id,
        "book_title": book.title,
        "member_id": member.id,
        "member_name": f"{member.first_name} {member.last_name}",
        "loan_date": db_loan.loan_date.isoformat() if db_loan.loan_date else None,
        "due_date": db_loan.due_date.isoformat() if db_loan.due_date else None,
        "timestamp": date.today().isoformat()
    })

    # 2. Real-time status posudbe
    await notify_loan_status(
        loan_id=db_loan.id,
        member_id=member.id,
        book_id=book.id,
        status="active",
        due_date=db_loan.due_date.isoformat() if db_loan.due_date else None,
        book_title=book.title,
        member_name=f"{member.first_name} {member.last_name}"
    )

    # 3. Real-time sinkronizacija (data_update)
    await notify_data_update(
        entity="loan",
        action="create",
        data={
            "id": db_loan.id,
            "book_id": book.id,
            "member_id": member.id,
            "loan_date": db_loan.loan_date.isoformat() if db_loan.loan_date else None,
            "due_date": db_loan.due_date.isoformat() if db_loan.due_date else None,
            "is_returned": False
        }
    )
    # ────────────────────────────────────────────────────────────────────────

    return db_loan


@router.patch("/{loan_id}/return", response_model=LoanOut)
async def return_book(loan_id: int, data: LoanReturn, db: Session = Depends(get_db)):
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Posudba nije pronađena")
    if loan.is_returned:
        raise HTTPException(status_code=400, detail="Knjiga je već vraćena")

    # Eksplicitno učitanje knjige
    book = db.query(Book).filter(Book.id == loan.book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")

    loan.is_returned = True
    # Konvertiraj string u date ako je potrebno
    from datetime import date as dt
    if isinstance(data.return_date, str):
        loan.return_date = dt.fromisoformat(data.return_date)
    else:
        loan.return_date = data.return_date

    book.available_copies += 1
    db.commit()
    db.refresh(loan)

    # ── WebSocket obavijesti (FAZA 1 & 2) ──────────────────────────────────
    member = loan.member

    # 1. Obavijest da je knjiga vraćena
    await manager.broadcast({
        "type": NotificationTypes.BOOK_RETURNED,
        "book_id": book.id,
        "book_title": book.title,
        "loan_id": loan.id,
        "return_date": loan.return_date.isoformat(),
        "timestamp": date.today().isoformat()
    })

    # 2. Real-time status posudbe - ažuriran
    member_name = (
        f"{member.first_name} {member.last_name}" if member else None
    )
    await notify_loan_status(
        loan_id=loan.id,
        member_id=member.id if member else None,
        book_id=book.id,
        status="returned",
        due_date=loan.due_date.isoformat(),
        return_date=loan.return_date.isoformat(),
        book_title=book.title,
        member_name=member_name
    )

    # 3. Real-time sinkronizacija (data_update)
    await notify_data_update(
        entity="loan",
        action="update",
        data={
            "id": loan.id,
            "book_id": book.id,
            "member_id": member.id if member else None,
            "is_returned": True,
            "return_date": loan.return_date.isoformat()
        }
    )
    # ────────────────────────────────────────────────────────────────────────

    return loan


@router.get("/stats/overdue", response_model=List[LoanOut])
def get_overdue_loans(db: Session = Depends(get_db)):
    return db.query(Loan).filter(
        Loan.is_returned == False,
        Loan.due_date < date.today()
    ).all()
