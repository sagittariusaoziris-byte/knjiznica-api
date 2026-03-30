from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, date
from app.database import get_db
from app.auth import require_staff, require_admin
from app.models.models import Book, Member, Loan

router = APIRouter(prefix="/sync", tags=["Sinkronizacija"])


def _parse_date(val):
    """Konvertira string datum u Python date objekt."""
    if val is None:
        return None
    if isinstance(val, date):
        return val
    try:
        return date.fromisoformat(str(val)[:10])
    except Exception:
        return None


def _get_all_data(db: Session):
    books = db.query(Book).all()
    members = db.query(Member).all()
    loans = db.query(Loan).all()

    def book_to_dict(b):
        return {
            "id": b.id, "isbn": b.isbn, "title": b.title, "author": b.author,
            "publisher": b.publisher, "year": b.year, "genre": b.genre,
            "total_copies": b.total_copies, "available_copies": b.available_copies,
            "description": b.description,
            "created_at": b.created_at.isoformat() if b.created_at else None
        }

    def member_to_dict(m):
        return {
            "id": m.id, "member_number": m.member_number,
            "first_name": m.first_name, "last_name": m.last_name,
            "email": m.email, "phone": m.phone, "address": m.address,
            "is_active": m.is_active,
            "joined_date": m.joined_date.isoformat() if m.joined_date else None,
            "created_at": m.created_at.isoformat() if m.created_at else None
        }

    def loan_to_dict(l):
        return {
            "id": l.id, "book_id": l.book_id, "member_id": l.member_id,
            "loan_date": l.loan_date.isoformat() if l.loan_date else None,
            "due_date": l.due_date.isoformat() if l.due_date else None,
            "return_date": l.return_date.isoformat() if l.return_date else None,
            "is_returned": l.is_returned, "notes": l.notes,
            "created_at": l.created_at.isoformat() if l.created_at else None,
            "updated_at": l.updated_at.isoformat() if hasattr(l, "updated_at") and l.updated_at else None
        }

    return {
        "books": [book_to_dict(b) for b in books],
        "members": [member_to_dict(m) for m in members],
        "loans": [loan_to_dict(l) for l in loans],
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/export")
async def export_all(db: Session = Depends(get_db), _=Depends(require_staff)):
    return _get_all_data(db)


@router.post("/import")
async def import_data(payload: dict, db: Session = Depends(get_db), _=Depends(require_admin)):
    stats = {"books": 0, "members": 0, "loans": 0, "errors": []}

    # Sinkroniziraj knjige
    for b in payload.get("books", []):
        try:
            existing = db.query(Book).filter(Book.id == b["id"]).first()
            if existing:
                for k, v in b.items():
                    if k not in ("id", "created_at") and hasattr(existing, k):
                        setattr(existing, k, v)
            else:
                book = Book(**{k: v for k, v in b.items()
                               if k not in ("created_at",) and hasattr(Book, k)})
                db.add(book)
            stats["books"] += 1
        except Exception as e:
            stats["errors"].append(f"Book {b.get('id')}: {str(e)}")

    # Sinkroniziraj članove
    for m in payload.get("members", []):
        try:
            existing = db.query(Member).filter(Member.id == m["id"]).first()
            if existing:
                for k, v in m.items():
                    if k not in ("id", "created_at") and hasattr(existing, k):
                        if k == "joined_date":
                            setattr(existing, k, _parse_date(v))
                        else:
                            setattr(existing, k, v)
            else:
                data = {k: v for k, v in m.items()
                        if k not in ("created_at",) and hasattr(Member, k)}
                if "joined_date" in data:
                    data["joined_date"] = _parse_date(data["joined_date"])
                member = Member(**data)
                db.add(member)
            stats["members"] += 1
        except Exception as e:
            stats["errors"].append(f"Member {m.get('id')}: {str(e)}")

    # Sinkroniziraj posudbe — datumi se konvertiraju u date objekte
    for l in payload.get("loans", []):
        try:
            existing = db.query(Loan).filter(Loan.id == l["id"]).first()
            if existing:
                for k, v in l.items():
                    if k not in ("id", "created_at") and hasattr(existing, k):
                        if k in ("loan_date", "due_date", "return_date"):
                            setattr(existing, k, _parse_date(v))
                        else:
                            setattr(existing, k, v)
            else:
                data = {k: v for k, v in l.items()
                        if k not in ("created_at",) and hasattr(Loan, k)}
                for date_field in ("loan_date", "due_date", "return_date"):
                    if date_field in data:
                        data[date_field] = _parse_date(data[date_field])
                loan = Loan(**data)
                db.add(loan)
            stats["loans"] += 1
        except Exception as e:
            stats["errors"].append(f"Loan {l.get('id')}: {str(e)}")

    db.commit()
    return {"status": "ok", "stats": stats, "timestamp": datetime.utcnow().isoformat()}


@router.get("/status")
async def sync_status(db: Session = Depends(get_db)):
    return {
        "status": "ok",
        "counts": {
            "books": db.query(Book).count(),
            "members": db.query(Member).count(),
            "loans": db.query(Loan).count(),
        },
        "timestamp": datetime.utcnow().isoformat()
    }
