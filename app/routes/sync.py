from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, date
from app.database import get_db
from app.auth import require_staff, require_admin
from app.models.models import Book, Member, Loan
from app.models.library import Library

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


# Polja koja se nikad ne prepisuju pri upsert (zaštita integriteta)
_BOOK_SKIP   = {"id", "created_at"}
_MEMBER_SKIP = {"id", "created_at"}
_LOAN_SKIP   = {"id", "created_at"}


def _get_all_data(db: Session):
    books     = db.query(Book).all()
    members   = db.query(Member).all()
    loans     = db.query(Loan).all()
    libraries = db.query(Library).all()

    def library_to_dict(lib):
        return {
            "id":         lib.id,
            "name":       lib.name,
            "slug":       lib.slug,
            "city":       lib.city,
            "address":    lib.address,
            "email":      lib.email,
            "phone":      lib.phone,
            "is_active":  lib.is_active,
            "notes":      lib.notes,
            "created_at": lib.created_at.isoformat() if lib.created_at else None,
        }

    def book_to_dict(b):
        return {
            "id": b.id,
            "library_id": b.library_id,          # ← multi-tenant
            "isbn": b.isbn, "title": b.title, "author": b.author,
            "publisher": b.publisher, "year": b.year, "genre": b.genre,
            "total_copies": b.total_copies, "available_copies": b.available_copies,
            "description": b.description,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "updated_at": b.updated_at.isoformat()   # ← za ISBN conflict resolution
                          if hasattr(b, "updated_at") and b.updated_at else None,
        }

    def member_to_dict(m):
        return {
            "id": m.id,
            "library_id": m.library_id,           # ← multi-tenant
            "member_number": m.member_number,
            "first_name": m.first_name, "last_name": m.last_name,
            "email": m.email, "phone": m.phone, "address": m.address,
            "is_active": m.is_active,
            "joined_date":  m.joined_date.isoformat()  if m.joined_date  else None,
            "created_at":   m.created_at.isoformat()   if m.created_at   else None,
        }

    def loan_to_dict(l):
        return {
            "id": l.id,
            "library_id": l.library_id,           # ← multi-tenant
            "book_id": l.book_id, "member_id": l.member_id,
            "loan_date":   l.loan_date.isoformat()   if l.loan_date   else None,
            "due_date":    l.due_date.isoformat()    if l.due_date    else None,
            "return_date": l.return_date.isoformat() if l.return_date else None,
            "is_returned": l.is_returned, "notes": l.notes,
            "created_at":  l.created_at.isoformat()  if l.created_at  else None,
            "updated_at":  l.updated_at.isoformat()
                           if hasattr(l, "updated_at") and l.updated_at else None,
        }

    return {
        "libraries": [library_to_dict(lib) for lib in libraries],
        "books":   [book_to_dict(b)   for b in books],
        "members": [member_to_dict(m) for m in members],
        "loans":   [loan_to_dict(l)   for l in loans],
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/export")
async def export_all(db: Session = Depends(get_db), _=Depends(require_staff)):
    return _get_all_data(db)


@router.post("/import")
async def import_data(payload: dict, db: Session = Depends(get_db), _=Depends(require_admin)):
    stats = {"libraries": 0, "books": 0, "members": 0, "loans": 0, "errors": []}

    # ── Knjižnice (UPSERT — prima ažurirane nazive s Render API servera) ──────
    for lib in payload.get("libraries", []):
        try:
            existing = db.query(Library).filter(Library.id == lib["id"]).first()
            if existing:
                for k in ("name", "slug", "city", "address", "email", "phone", "is_active", "notes"):
                    if k in lib and hasattr(existing, k):
                        setattr(existing, k, lib[k])
            else:
                safe = {k: v for k, v in lib.items()
                        if k not in {"id", "created_at"} and hasattr(Library, k)}
                db.add(Library(**safe))
            stats["libraries"] += 1
        except Exception as e:
            stats["errors"].append(f"Library {lib.get('id')}: {str(e)}")

    # ── Knjige ────────────────────────────────────────────────────────────────
    for b in payload.get("books", []):
        try:
            existing = db.query(Book).filter(Book.id == b["id"]).first()
            if existing:
                for k, v in b.items():
                    if k not in _BOOK_SKIP and hasattr(existing, k):
                        setattr(existing, k, v)
            else:
                book = Book(**{k: v for k, v in b.items()
                               if k not in _BOOK_SKIP and hasattr(Book, k)})
                db.add(book)
            stats["books"] += 1
        except Exception as e:
            stats["errors"].append(f"Book {b.get('id')}: {str(e)}")

    # ── Članovi ───────────────────────────────────────────────────────────────
    for m in payload.get("members", []):
        try:
            existing = db.query(Member).filter(Member.id == m["id"]).first()
            if existing:
                for k, v in m.items():
                    if k not in _MEMBER_SKIP and hasattr(existing, k):
                        setattr(existing, k, _parse_date(v) if k == "joined_date" else v)
            else:
                data = {k: v for k, v in m.items()
                        if k not in _MEMBER_SKIP and hasattr(Member, k)}
                if "joined_date" in data:
                    data["joined_date"] = _parse_date(data["joined_date"])
                db.add(Member(**data))
            stats["members"] += 1
        except Exception as e:
            stats["errors"].append(f"Member {m.get('id')}: {str(e)}")

    # ── Posudbe ───────────────────────────────────────────────────────────────
    for l in payload.get("loans", []):
        try:
            existing = db.query(Loan).filter(Loan.id == l["id"]).first()
            if existing:
                for k, v in l.items():
                    if k not in _LOAN_SKIP and hasattr(existing, k):
                        setattr(existing, k,
                                _parse_date(v) if k in ("loan_date", "due_date", "return_date") else v)
            else:
                data = {k: v for k, v in l.items()
                        if k not in _LOAN_SKIP and hasattr(Loan, k)}
                for df in ("loan_date", "due_date", "return_date"):
                    if df in data:
                        data[df] = _parse_date(data[df])
                db.add(Loan(**data))
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
            "libraries": db.query(Library).count(),
            "books":     db.query(Book).count(),
            "members":   db.query(Member).count(),
            "loans":     db.query(Loan).count(),
        },
        "timestamp": datetime.utcnow().isoformat(),
    }
