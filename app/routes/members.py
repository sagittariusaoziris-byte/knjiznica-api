"""
app/routes/members.py
VERZIJA: 9.1.4 — Paginacija (PagedResponse) na list endpointu
"""
import random
import string
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_library_id, require_staff
from app.database import get_db
from app.models.models import Member
from app.models.user import User
from app.schemas.schemas import MemberCreate, MemberOut, MemberUpdate, PagedResponse

router = APIRouter(prefix="/members", tags=["Članovi"])


def _members_query(db: Session, library_id: Optional[int]):
    q = db.query(Member)
    if library_id is not None:
        q = q.filter(Member.library_id == library_id)
    return q


def generate_member_number():
    return "KNJ-" + "".join(random.choices(string.digits, k=6))


@router.get("/", response_model=PagedResponse[MemberOut])
def get_members(
    skip: int = Query(0, ge=0, description="Broj zapisa koje preskočiti"),
    limit: int = Query(50, ge=1, le=200, description="Maks. zapisa po stranici (max 200)"),
    search: Optional[str] = Query(None),
    member_number: Optional[str] = Query(None),
    active_only: bool = False,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    query = _members_query(db, library_id)
    if search:
        query = query.filter(
            (Member.first_name.ilike(f"%{search}%")) |
            (Member.last_name.ilike(f"%{search}%")) |
            (Member.email.ilike(f"%{search}%"))
        )
    if member_number:
        query = query.filter(Member.member_number == member_number)
    if active_only:
        query = query.filter(Member.is_active == True)
    total = query.count()
    items = query.offset(skip).limit(limit).all()
    return PagedResponse.create(items=items, total=total, skip=skip, limit=limit)


@router.get("/{member_id}", response_model=MemberOut)
def get_member(
    member_id: int,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    member = _members_query(db, library_id).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Član nije pronađen")
    return member


@router.get("/number/{member_number}", response_model=MemberOut)
def get_member_by_number(
    member_number: str,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    member = _members_query(db, library_id).filter(Member.member_number == member_number).first()
    if not member:
        raise HTTPException(status_code=404, detail="Član nije pronađen")
    return member


@router.post("/", response_model=MemberOut, status_code=201)
def create_member(
    member: MemberCreate,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db)
):
    if not current_user.library_id:
        raise HTTPException(status_code=400, detail="Korisnik nije dodijeljen knjižnici")

    if member.email:
        existing = db.query(Member).filter(
            Member.library_id == current_user.library_id,
            Member.email == member.email
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Član s tim emailom već postoji")

    while True:
        num = generate_member_number()
        if not db.query(Member).filter(
            Member.library_id == current_user.library_id,
            Member.member_number == num
        ).first():
            break

    db_member = Member(**member.model_dump(), member_number=num, library_id=current_user.library_id)
    db.add(db_member)
    db.commit()
    db.refresh(db_member)
    return db_member


@router.put("/{member_id}", response_model=MemberOut)
def update_member(
    member_id: int,
    data: MemberUpdate,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db)
):
    member = _members_query(db, current_user.library_id).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Član nije pronađen")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(member, f, v)
    db.commit()
    db.refresh(member)
    return member


@router.delete("/{member_id}", status_code=204)
def delete_member(
    member_id: int,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db)
):
    member = _members_query(db, current_user.library_id).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Član nije pronađen")
    db.delete(member)
    db.commit()
