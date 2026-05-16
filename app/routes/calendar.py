"""
app/routes/calendar.py
VERZIJA: 9.1.0 — library_id filter na SVIM rutama

ISPRAVCI:
  - SVAKI endpoint je bio bez library_id filtera → curenje podataka između knjižnica
  - Dodano get_library_id dependency u sve funkcije
  - bulk-renew sada ograničen na knjižnicu korisnika
  - get_member_calendar provjerava da član pripada knjižnici
"""

from datetime import date, timedelta
from typing import List, Optional

from app.auth import get_library_id, require_staff
from app.database import get_db
from app.models.models import Book, Loan, Member
from app.models.user import User
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

router = APIRouter(prefix="/calendar", tags=["Kalendar"])


def _loan_query(db: Session, library_id: Optional[int]):
    """Centralni query za posudbe — uvijek filtrira po library_id."""
    q = db.query(Loan)
    if library_id is not None:
        q = q.filter(Loan.library_id == library_id)
    return q


def _build_loan_item(loan, db: Session, library_id: Optional[int], extra: dict = None):
    """Izgradi dict za loan — dohvaća member i book filtrirane po library_id."""
    mq = db.query(Member).filter(Member.id == loan.member_id)
    if library_id is not None:
        mq = mq.filter(Member.library_id == library_id)
    member = mq.first()

    bq = db.query(Book).filter(Book.id == loan.book_id)
    if library_id is not None:
        bq = bq.filter(Book.library_id == library_id)
    book = bq.first()

    if not member or not book:
        return None

    item = {
        "loan_id": loan.id,
        "book": {
            "id": book.id,
            "title": book.title,
            "author": book.author,
            "isbn": book.isbn,
            "shelf": book.shelf,
        },
        "member": {
            "id": member.id,
            "name": f"{member.first_name} {member.last_name}",
            "email": member.email,
            "phone": member.phone,
        },
        "loan_date": loan.loan_date.isoformat(),
        "due_date": loan.due_date.isoformat(),
    }
    if extra:
        item.update(extra)
    return item


@router.get("/due-today")
def get_due_today(
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db),
):
    """Knjige koje danas istječu — filtrirano po knjižnici."""
    today = date.today()
    loans = _loan_query(db, library_id).filter(
        Loan.is_returned == False,
        Loan.due_date == today,
    ).all()

    result = [
        item for loan in loans
        if (item := _build_loan_item(loan, db, library_id, {"status": "due_today"}))
    ]
    return {"date": today.isoformat(), "total": len(result), "loans": result}


@router.get("/upcoming")
def get_upcoming(
    days: Optional[int] = Query(7, ge=1, le=30, description="Broj dana unaprijed"),
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db),
):
    """Predstojeći rokovi — filtrirani po knjižnici."""
    today = date.today()
    end_date = today + timedelta(days=days)

    loans = _loan_query(db, library_id).filter(
        Loan.is_returned == False,
        Loan.due_date >= today,
        Loan.due_date <= end_date,
    ).order_by(Loan.due_date).all()

    result = [
        item for loan in loans
        if (item := _build_loan_item(
            loan, db, library_id,
            {"days_until_due": (loan.due_date - today).days, "status": "upcoming"}
        ))
    ]
    return {
        "date_range": {"from": today.isoformat(), "to": end_date.isoformat()},
        "total": len(result),
        "loans": result,
    }


@router.get("/overdue")
def get_overdue(
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db),
):
    """Kasneci zajmovi — filtrirani po knjižnici."""
    today = date.today()
    loans = _loan_query(db, library_id).filter(
        Loan.is_returned == False,
        Loan.due_date < today,
    ).order_by(Loan.due_date).all()

    result = [
        item for loan in loans
        if (item := _build_loan_item(
            loan, db, library_id,
            {"days_overdue": (today - loan.due_date).days, "status": "overdue"}
        ))
    ]
    return {"date": today.isoformat(), "total": len(result), "loans": result}


@router.post("/bulk-renew")
def bulk_renew(
    days: Optional[int] = Query(7, ge=1, le=30, description="Broj dana za produženje"),
    loan_ids: Optional[List[int]] = Query(None, description="Lista ID-eva posudbi"),
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """
    Masovno produženje posudbi — ograničeno na knjižnicu korisnika.

    ISPRAVAK: Ranije nije filtriralo po library_id — knjiznicar jedne knjiznice
    mogao je produziti posudbe druge knjiznice.
    """
    library_id = current_user.library_id
    base_q = _loan_query(db, library_id).filter(Loan.is_returned == False)
    loans = base_q.filter(Loan.id.in_(loan_ids)).all() if loan_ids else base_q.all()

    if not loans:
        raise HTTPException(status_code=404, detail="Nema posudbi za produženje")

    results = []
    for loan in loans:
        old_due_date = loan.due_date
        loan.due_date = loan.due_date + timedelta(days=days)
        results.append({
            "loan_id": loan.id,
            "old_due_date": old_due_date.isoformat(),
            "new_due_date": loan.due_date.isoformat(),
            "days_added": days,
        })

    db.commit()
    return {
        "message": f"Uspješno produženih {len(results)} posudbi",
        "days_added": days,
        "renewed": results,
    }


@router.get("/summary")
def get_calendar_summary(
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db),
):
    """Sažetak kalendara — filtriran po knjižnici."""
    today = date.today()
    lq = _loan_query(db, library_id)

    due_today    = lq.filter(Loan.is_returned == False, Loan.due_date == today).count()
    overdue      = lq.filter(Loan.is_returned == False, Loan.due_date < today).count()
    upcoming_7   = lq.filter(Loan.is_returned == False, Loan.due_date >= today,
                             Loan.due_date <= today + timedelta(days=7)).count()
    upcoming_30  = lq.filter(Loan.is_returned == False, Loan.due_date >= today,
                             Loan.due_date <= today + timedelta(days=30)).count()
    active_total = lq.filter(Loan.is_returned == False).count()

    return {
        "date": today.isoformat(),
        "summary": {
            "due_today": due_today,
            "overdue": overdue,
            "upcoming_7_days": upcoming_7,
            "upcoming_30_days": upcoming_30,
            "active_total": active_total,
        },
        "alerts": {
            "has_overdue": overdue > 0,
            "has_due_today": due_today > 0,
            "overdue_count": overdue,
            "due_today_count": due_today,
        },
    }


@router.get("/by-date/{target_date}")
def get_by_date(
    target_date: date,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db),
):
    """Posudbe za određeni datum — filtrirani po knjižnici."""
    loans = _loan_query(db, library_id).filter(
        Loan.is_returned == False,
        Loan.due_date == target_date,
    ).all()

    result = [
        item for loan in loans
        if (item := _build_loan_item(loan, db, library_id))
    ]
    return {"date": target_date.isoformat(), "total": len(result), "loans": result}


@router.get("/member/{member_id}")
def get_member_calendar(
    member_id: int,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db),
):
    """
    Kalendar za određenog člana — provjerava da član pripada knjižnici.

    ISPRAVAK: Ranije nije provjeravalo library_id — admin jedne knjiznice
    mogao je vidjeti posudbe clana iz druge knjiznice.
    """
    mq = db.query(Member).filter(Member.id == member_id)
    if library_id is not None:
        mq = mq.filter(Member.library_id == library_id)
    member = mq.first()
    if not member:
        raise HTTPException(status_code=404, detail="Član nije pronađen")

    today = date.today()
    loans = _loan_query(db, library_id).filter(
        Loan.member_id == member_id,
        Loan.is_returned == False,
    ).order_by(Loan.due_date).all()

    result = []
    for loan in loans:
        bq = db.query(Book).filter(Book.id == loan.book_id)
        if library_id is not None:
            bq = bq.filter(Book.library_id == library_id)
        book = bq.first()
        if not book:
            continue

        days_until_due = (loan.due_date - today).days
        status = "overdue" if days_until_due < 0 else "due_today" if days_until_due == 0 else "upcoming"

        result.append({
            "loan_id": loan.id,
            "book": {
                "id": book.id,
                "title": book.title,
                "author": book.author,
                "shelf": book.shelf,
            },
            "loan_date": loan.loan_date.isoformat(),
            "due_date": loan.due_date.isoformat(),
            "days_until_due": days_until_due,
            "status": status,
        })

    return {
        "member": {
            "id": member.id,
            "name": f"{member.first_name} {member.last_name}",
            "member_number": member.member_number,
        },
        "total_active": len(result),
        "loans": result,
    }
