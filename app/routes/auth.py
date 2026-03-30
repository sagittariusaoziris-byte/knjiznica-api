from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from app.database import get_db
from app.models.user import User, UserRole
from app.auth import (authenticate_user, create_access_token, hash_password,
                      get_current_user, require_admin, require_staff)

router = APIRouter(prefix="/auth", tags=["Autentikacija"])


class Token(BaseModel):
    access_token: str
    token_type: str
    role: str
    full_name: str

class UserCreate(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: UserRole = UserRole.knjiznicar

class UserOut(BaseModel):
    id: int
    username: str
    full_name: Optional[str]
    email: Optional[str]
    role: UserRole
    is_active: bool
    plain_password: Optional[str] = None  # Vraća se samo adminu

    class Config:
        from_attributes = True

class PasswordChange(BaseModel):
    old_password: str
    new_password: str


@router.post("/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Pogrešno korisničko ime ili lozinka")
    token = create_access_token({"sub": user.username, "role": user.role})
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "full_name": user.full_name or user.username
    }

@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@router.get("/users", response_model=List[UserOut])
async def get_users(db: Session = Depends(get_db), _=Depends(require_admin)):
    return db.query(User).all()

@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(data: UserCreate, db: Session = Depends(get_db), _=Depends(require_admin)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Korisničko ime već postoji")
    user = User(
        username=data.username,
        full_name=data.full_name,
        email=data.email,
        role=data.role,
        hashed_password=hash_password(data.password),
        plain_password=data.password  # Spremi plain text za prikaz adminu
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@router.put("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: int, data: UserCreate, db: Session = Depends(get_db), _=Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Korisnik nije pronađen")
    if data.username != user.username and db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Korisničko ime već postoji")
    user.username = data.username
    user.full_name = data.full_name
    user.email = data.email
    user.role = data.role
    if data.password:
        user.hashed_password = hash_password(data.password)
        user.plain_password = data.password
    db.commit()
    db.refresh(user)
    return user

@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: int, db: Session = Depends(get_db), current=Depends(require_admin)):
    if current.id == user_id:
        raise HTTPException(status_code=400, detail="Ne možete obrisati sami sebe")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Korisnik nije pronađen")
    db.delete(user)
    db.commit()

@router.post("/change-password")
async def change_password(data: PasswordChange, db: Session = Depends(get_db),
                          current: User = Depends(get_current_user)):
    from app.auth import verify_password
    if not verify_password(data.old_password, current.hashed_password):
        raise HTTPException(status_code=400, detail="Stara lozinka nije ispravna")
    current.hashed_password = hash_password(data.new_password)
    db.commit()
    return {"detail": "Lozinka promijenjena"}


class LinkMemberRequest(BaseModel):
    member_number: str


@router.post("/link-member")
async def link_member(
    data: LinkMemberRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Poveži korisnika s brojem člana."""
    from app.models.models import Member
    member = db.query(Member).filter(
        Member.member_number == data.member_number,
        Member.is_active == True
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Član s tim brojem nije pronađen")

    current_user.member_id = member.id
    db.commit()
    return {
        "success": True,
        "member_id": member.id,
        "member_number": member.member_number,
        "full_name": f"{member.first_name} {member.last_name}",
        "email": member.email,
        "phone": member.phone,
    }


@router.get("/my-member")
async def get_my_member(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Dohvati povezanog člana za trenutnog korisnika."""
    if not current_user.member_id:
        return {"linked": False}
    from app.models.models import Member
    member = db.query(Member).filter(Member.id == current_user.member_id).first()
    if not member:
        return {"linked": False}
    return {
        "linked": True,
        "member_id": member.id,
        "member_number": member.member_number,
        "full_name": f"{member.first_name} {member.last_name}",
        "email": member.email,
        "phone": member.phone,
        "address": member.address,
        "joined_date": member.joined_date.isoformat() if member.joined_date else None,
    }
