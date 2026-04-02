from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import random, string
from app.database import get_db
from app.models.models import Member
from app.schemas.schemas import MemberCreate, MemberUpdate, MemberOut

router = APIRouter(prefix="/members", tags=["Članovi"])


def generate_member_number():
    return "KNJ-" + "".join(random.choices(string.digits, k=6))


@router.get("/", response_model=List[MemberOut])
def get_members(
    skip: int = 0,
    limit: int = 50,
    search: Optional[str] = Query(None, description="Pretraži po imenu ili emailu"),
    member_number: Optional[str] = Query(None, description="Pretraži po broju člana"),
    active_only: bool = False,
    db: Session = Depends(get_db)
):
    query = db.query(Member)
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
    return query.offset(skip).limit(limit).all()


@router.get("/{member_id}", response_model=MemberOut)
def get_member(member_id: int, db: Session = Depends(get_db)):
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Član nije pronađen")
    return member


@router.get("/number/{member_number}", response_model=MemberOut)
def get_member_by_number(member_number: str, db: Session = Depends(get_db)):
    member = db.query(Member).filter(Member.member_number == member_number).first()
    if not member:
        raise HTTPException(status_code=404, detail="Član nije pronađen")
    return member


@router.post("/", response_model=MemberOut, status_code=201)
def create_member(member: MemberCreate, db: Session = Depends(get_db)):
    if member.email:
        existing = db.query(Member).filter(Member.email == member.email).first()
        if existing:
            raise HTTPException(status_code=400, detail="Član s tim emailom već postoji")
    member_number = generate_member_number()
    while db.query(Member).filter(Member.member_number == member_number).first():
        member_number = generate_member_number()
    db_member = Member(**member.model_dump(), member_number=member_number)
    db.add(db_member)
    db.commit()
    db.refresh(db_member)
    return db_member


@router.put("/{member_id}", response_model=MemberOut)
def update_member(member_id: int, member: MemberUpdate, db: Session = Depends(get_db)):
    db_member = db.query(Member).filter(Member.id == member_id).first()
    if not db_member:
        raise HTTPException(status_code=404, detail="Član nije pronađen")
    update_data = member.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_member, key, value)
    db.commit()
    db.refresh(db_member)
    return db_member


@router.delete("/{member_id}", status_code=204)
def delete_member(member_id: int, db: Session = Depends(get_db)):
    db_member = db.query(Member).filter(Member.id == member_id).first()
    if not db_member:
        raise HTTPException(status_code=404, detail="Član nije pronađen")
    db.delete(db_member)
    db.commit()
