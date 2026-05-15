"""
Calendar routes for Knjižnica API
Kalender i raspored za upravljanje rokovima posudbi.
"""

from datetime import date, datetime, timedelta
from typing import List, Optional

from app.database import get_db
from app.models.models import Book, Loan, Member
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

router = APIRouter(prefix="/calendar", tags=["Kalendar"])


@router.get("/due-today")
def get_due_today(db: Session = Depends(get_db)):
    """
    Knjige koje danas istječu.

    Vraća sve posudbe kojima je danas rok za povratak.
    """
    today = date.today()

    due_today = (
        db.query(Loan)
        .filter(
            Loan.is_returned == False,
            Loan.due_date == today
        )
        .all()
    )

    result = []
    for loan in due_today:
        member = db.query(Member).filter(Member.id == loan.member_id).first()
        book = db.query(Book).filter(Book.id == loan.book_id).first()

        if member and book:
            result.append({
                "loan_id": loan.id,
                "book": {
                    "id": book.id,
                    "title": book.title,
                    "author": book.author,
                    "isbn": book.isbn,
                    "shelf": book.shelf
                },
                "member": {
                    "id": member.id,
                    "name": f"{member.first_name} {member.last_name}",
                    "email": member.email,
                    "phone": member.phone
                },
                "loan_date": loan.loan_date.isoformat(),
                "due_date": loan.due_date.isoformat(),
                "status": "due_today"
            })

    return {
        "date": today.isoformat(),
        "total": len(result),
        "loans": result
    }


@router.get("/upcoming")
def get_upcoming(
    days: Optional[int] = Query(7, ge=1, le=30, description="Broj dana unaprijed"),
    db: Session = Depends(get_db)
):
    """
    Predstojeći rokovi.

    Vraća sve posudbe koje istječu u narednih N dana.

    - **days**: Broj dana unaprijed (1-30)
    """
    today = date.today()
    end_date = today + timedelta(days=days)

    upcoming = (
        db.query(Loan)
        .filter(
            Loan.is_returned == False,
            Loan.due_date >= today,
            Loan.due_date <= end_date
        )
        .order_by(Loan.due_date)
        .all()
    )

    result = []
    for loan in upcoming:
        member = db.query(Member).filter(Member.id == loan.member_id).first()
        book = db.query(Book).filter(Book.id == loan.book_id).first()

        if member and book:
            days_until_due = (loan.due_date - today).days
            result.append({
                "loan_id": loan.id,
                "book": {
                    "id": book.id,
                    "title": book.title,
                    "author": book.author,
                    "isbn": book.isbn,
                    "shelf": book.shelf
                },
                "member": {
                    "id": member.id,
                    "name": f"{member.first_name} {member.last_name}",
                    "email": member.email,
                    "phone": member.phone
                },
                "loan_date": loan.loan_date.isoformat(),
                "due_date": loan.due_date.isoformat(),
                "days_until_due": days_until_due,
                "status": "upcoming"
            })

    return {
        "date_range": {
            "from": today.isoformat(),
            "to": end_date.isoformat()
        },
        "total": len(result),
        "loans": result
    }


@router.get("/overdue")
def get_overdue(db: Session = Depends(get_db)):
    """
    Kašnjenja.

    Vraća sve posudbe koje kasne (prošao je rok za povratak).
    """
    today = date.today()

    overdue = (
        db.query(Loan)
        .filter(
            Loan.is_returned == False,
            Loan.due_date < today
        )
        .order_by(Loan.due_date)
        .all()
    )

    result = []
    for loan in overdue:
        member = db.query(Member).filter(Member.id == loan.member_id).first()
        book = db.query(Book).filter(Book.id == loan.book_id).first()

        if member and book:
            days_overdue = (today - loan.due_date).days
            result.append({
                "loan_id": loan.id,
                "book": {
                    "id": book.id,
                    "title": book.title,
                    "author": book.author,
                    "isbn": book.isbn,
                    "shelf": book.shelf
                },
                "member": {
                    "id": member.id,
                    "name": f"{member.first_name} {member.last_name}",
                    "email": member.email,
                    "phone": member.phone
                },
                "loan_date": loan.loan_date.isoformat(),
                "due_date": loan.due_date.isoformat(),
                "days_overdue": days_overdue,
                "status": "overdue"
            })

    return {
        "date": today.isoformat(),
        "total": len(result),
        "loans": result
    }


@router.post("/bulk-renew")
def bulk_renew(
    days: Optional[int] = Query(7, ge=1, le=30, description="Broj dana za produženje"),
    loan_ids: Optional[List[int]] = Query(None, description="Lista ID-eva posudbi za produženje"),
    db: Session = Depends(get_db)
):
    """
    Masovno produženje posudbi.

    Produžava rok za povratak za odabrane posudbe.

    - **days**: Broj dana za produženje (1-30)
    - **loan_ids**: Lista ID-eva posudbi (ako nije navedeno, produžava sve aktivne)
    """
    if days is None:
        days = 7

    # Ako nisu navedeni loan_ids, uzmi sve aktivne posudbe
    if loan_ids is None:
        loans = db.query(Loan).filter(Loan.is_returned == False).all()
    else:
        loans = db.query(Loan).filter(Loan.id.in_(loan_ids)).all()

    if not loans:
        raise HTTPException(status_code=404, detail="Nema posudbi za produženje")

    renewed_count = 0
    results = []

    for loan in loans:
        # Produži rok
        old_due_date = loan.due_date
        loan.due_date = loan.due_date + timedelta(days=days)

        renewed_count += 1
        results.append({
            "loan_id": loan.id,
            "old_due_date": old_due_date.isoformat(),
            "new_due_date": loan.due_date.isoformat(),
            "days_added": days
        })

    db.commit()

    return {
        "message": f"Uspješno produženih {renewed_count} posudbi",
        "days_added": days,
        "renewed": results
    }


@router.get("/summary")
def get_calendar_summary(
    db: Session = Depends(get_db)
):
    """
    Sažetak kalendara.

    Brzi pregled svih kategorija posudbi.
    """
    today = date.today()

    # Due today
    due_today = db.query(Loan).filter(
        Loan.is_returned == False,
        Loan.due_date == today
    ).count()

    # Overdue
    overdue = db.query(Loan).filter(
        Loan.is_returned == False,
        Loan.due_date < today
    ).count()

    # Upcoming (next 7 days)
    upcoming_7 = db.query(Loan).filter(
        Loan.is_returned == False,
        Loan.due_date >= today,
        Loan.due_date <= today + timedelta(days=7)
    ).count()

    # Upcoming (next 30 days)
    upcoming_30 = db.query(Loan).filter(
        Loan.is_returned == False,
        Loan.due_date >= today,
        Loan.due_date <= today + timedelta(days=30)
    ).count()

    # Active loans total
    active_total = db.query(Loan).filter(Loan.is_returned == False).count()

    return {
        "date": today.isoformat(),
        "summary": {
            "due_today": due_today,
            "overdue": overdue,
            "upcoming_7_days": upcoming_7,
            "upcoming_30_days": upcoming_30,
            "active_total": active_total
        },
        "alerts": {
            "has_overdue": overdue > 0,
            "has_due_today": due_today > 0,
            "overdue_count": overdue,
            "due_today_count": due_today
        }
    }


@router.get("/by-date/{target_date}")
def get_by_date(
    target_date: date,
    db: Session = Depends(get_db)
):
    """
    Posudbe za određeni datum.

    Vraća sve posudbe kojima je rok za povratak na određeni datum.

    - **target_date**: Datum (format: YYYY-MM-DD)
    """
    loans = (
        db.query(Loan)
        .filter(
            Loan.is_returned == False,
            Loan.due_date == target_date
        )
        .all()
    )

    result = []
    for loan in loans:
        member = db.query(Member).filter(Member.id == loan.member_id).first()
        book = db.query(Book).filter(Book.id == loan.book_id).first()

        if member and book:
            result.append({
                "loan_id": loan.id,
                "book": {
                    "id": book.id,
                    "title": book.title,
                    "author": book.author
                },
                "member": {
                    "id": member.id,
                    "name": f"{member.first_name} {member.last_name}",
                    "email": member.email
                },
                "loan_date": loan.loan_date.isoformat(),
                "due_date": loan.due_date.isoformat()
            })

    return {
        "date": target_date.isoformat(),
        "total": len(result),
        "loans": result
    }


@router.get("/member/{member_id}")
def get_member_calendar(
    member_id: int,
    db: Session = Depends(get_db)
):
    """
    Kalendar za određenog člana.

    Vraća sve aktivne posudbe člana s rokovima.
    """
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Član nije pronađen")

    today = date.today()

    # Aktivne posudbe
    active_loans = (
        db.query(Loan)
        .filter(
            Loan.member_id == member_id,
            Loan.is_returned == False
        )
        .order_by(Loan.due_date)
        .all()
    )

    result = []
    for loan in active_loans:
        book = db.query(Book).filter(Book.id == loan.book_id).first()
        days_until_due = (loan.due_date - today).days

        if book:
            status = "overdue" if days_until_due < 0 else "due_today" if days_until_due == 0 else "upcoming"

            result.append({
                "loan_id": loan.id,
                "book": {
                    "id": book.id,
                    "title": book.title,
                    "author": book.author,
                    "shelf": book.shelf
                },
                "loan_date": loan.loan_date.isoformat(),
                "due_date": loan.due_date.isoformat(),
                "days_until_due": days_until_due,
                "status": status
            })

    return {
        "member": {
            "id": member.id,
            "name": f"{member.first_name} {member.last_name}",
            "member_number": member.member_number
        },
        "total_active": len(result),
        "loans": result
    }
