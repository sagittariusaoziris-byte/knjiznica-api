"""
app/routes/libraries.py — VERZIJA 9.0.0
Admin upravljanje knjižnicama (tenantima).
Samo globalni admin (library_id=None) ima puni pristup.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin, require_staff
from app.database import get_db
from app.models.library import Library
from app.models.user import User

router = APIRouter(prefix="/libraries", tags=["Knjižnice (Admin)"])


class LibraryCreate(BaseModel):
    name: str
    slug: str
    city: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


class LibraryOut(BaseModel):
    id: int
    name: str
    slug: str
    city: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool
    notes: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/", response_model=List[LibraryOut])
def get_libraries(
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db)
):
    """Lista knjižnica — admin vidi sve, knjižničar samo svoju."""
    if current_user.library_id:
        # Library admin ili knjižničar vide samo svoju knjižnicu
        return db.query(Library).filter(Library.id == current_user.library_id).all()
    return db.query(Library).all()


@router.get("/{library_id}", response_model=LibraryOut)
def get_library(
    library_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    # Library admin može vidjeti samo svoju
    if current_user.library_id and current_user.library_id != library_id:
        raise HTTPException(status_code=403, detail="Pristup odbijen")
    lib = db.query(Library).filter(Library.id == library_id).first()
    if not lib:
        raise HTTPException(status_code=404, detail="Knjižnica nije pronađena")
    return lib


@router.post("/", response_model=LibraryOut, status_code=201)
def create_library(
    data: LibraryCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Kreiraj novu knjižnicu — samo globalni admin."""
    if current_user.library_id:
        raise HTTPException(status_code=403, detail="Samo globalni admin može kreirati knjižnice")
    if db.query(Library).filter(Library.slug == data.slug).first():
        raise HTTPException(status_code=400, detail=f"Slug '{data.slug}' već postoji")
    lib = Library(**data.model_dump())
    db.add(lib)
    db.commit()
    db.refresh(lib)
    return lib


@router.put("/{library_id}", response_model=LibraryOut)
def update_library(
    library_id: int,
    data: LibraryCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    if current_user.library_id and current_user.library_id != library_id:
        raise HTTPException(status_code=403, detail="Pristup odbijen")
    lib = db.query(Library).filter(Library.id == library_id).first()
    if not lib:
        raise HTTPException(status_code=404, detail="Knjižnica nije pronađena")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(lib, f, v)
    db.commit()
    db.refresh(lib)
    return lib


@router.post("/{library_id}/deactivate")
def deactivate_library(
    library_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    if current_user.library_id:
        raise HTTPException(status_code=403, detail="Samo globalni admin")
    lib = db.query(Library).filter(Library.id == library_id).first()
    if not lib:
        raise HTTPException(status_code=404, detail="Knjižnica nije pronađena")
    lib.is_active = False
    db.commit()
    return {"success": True, "message": f"Knjižnica {lib.name} deaktivirana"}


@router.get("/{library_id}/stats")
def get_library_stats(
    library_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Brza statistika po knjižnici za admin dashboard."""
    if current_user.library_id and current_user.library_id != library_id:
        raise HTTPException(status_code=403, detail="Pristup odbijen")
    from app.models.models import Book, Member, Loan
    from datetime import date
    return {
        "library_id": library_id,
        "books":   db.query(Book).filter(Book.library_id == library_id).count(),
        "members": db.query(Member).filter(Member.library_id == library_id).count(),
        "active_loans": db.query(Loan).filter(
            Loan.library_id == library_id, Loan.is_returned == False).count(),
        "overdue_loans": db.query(Loan).filter(
            Loan.library_id == library_id, Loan.is_returned == False,
            Loan.due_date < date.today()).count(),
    }
