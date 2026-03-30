from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date
from app.database import get_db
from app.models.models import Loan, Book, Member
from app.schemas.schemas import LoanCreate, LoanReturn, LoanOut

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
def create_loan(loan: LoanCreate, db: Session = Depends(get_db)):
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
    return db_loan


@router.patch("/{loan_id}/return", response_model=LoanOut)
def return_book(loan_id: int, data: LoanReturn, db: Session = Depends(get_db)):
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Posudba nije pronađena")
    if loan.is_returned:
        raise HTTPException(status_code=400, detail="Knjiga je već vraćena")

    loan.is_returned = True
    loan.return_date = data.return_date
    loan.book.available_copies += 1
    db.commit()
    db.refresh(loan)
    return loan


@router.get("/stats/overdue", response_model=List[LoanOut])
def get_overdue_loans(db: Session = Depends(get_db)):
    return db.query(Loan).filter(
        Loan.is_returned == False,
        Loan.due_date < date.today()
    ).all()
