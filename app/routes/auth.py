"""
app/routes/auth.py
VERZIJA: 9.4.7 — library_id u update_user + library_name u /auth/me

IZMJENE v9.4.7:
  - update_user: PUT /auth/users/{id} sada ažurira library_id (paritet s API-jem)
  - /auth/me: UserOut schema sada uključuje library_name
  - /libraries/ GET: dostupan i knjiznicar ulozi

IZMJENE v9.2.0:
  - plain_password se enkriptira pri pohrani (Fernet, app/password_crypto.py)
  - plain_password se dekriptira samo za ovlaštene admine:
      * Super admin (library_id=None) → vidi sve lozinke svih knjižnica
      * Library admin (library_id=X)  → vidi samo lozinke svoje knjižnice
      * Ostali korisnici               → plain_password = None
  - Login endpoint zaštićen od brute-force napada:
      5 neuspjelih pokušaja → 15 minuta blokade po IP-u
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import (ACCESS_TOKEN_EXPIRE_MINUTES, authenticate_user,
                      create_access_token, get_current_user, get_library_id,
                      hash_password, require_admin, require_staff)
from app.database import get_db
from app.models.library import Library
from app.models.user import User, UserRole
from app.password_crypto import decrypt_password, encrypt_password
from app.rate_limiter import login_rate_limiter

router = APIRouter(prefix="/auth", tags=["Autentikacija"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str
    role: str
    full_name: str
    library_id: Optional[int] = None
    library_name: Optional[str] = None
    expires_in: int


class UserCreate(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: UserRole = UserRole.knjiznicar
    library_id: Optional[int] = None


class UserOut(BaseModel):
    id: int
    username: str
    full_name: Optional[str]
    email: Optional[str]
    role: UserRole
    is_active: bool
    library_id: Optional[int] = None
    plain_password: Optional[str] = None   # Dekriptirana – vidljiva samo adminu

    class Config:
        from_attributes = True


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_client_ip(request: Request) -> str:
    """Dohvati stvarnu IP adresu klijenta (uzima u obzir reverse proxy)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _user_to_out(user: User, show_password: bool) -> dict:
    """Pretvori User u dict za response – kontrolira vidljivost lozinke."""
    plain = decrypt_password(user.plain_password) if show_password else None
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "library_id": user.library_id,
        "plain_password": plain,
    }


def _can_see_passwords(current_user: User) -> bool:
    """True ako korisnik smije vidjeti plain_password vrijednosti."""
    return current_user.role == UserRole.admin


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/token", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Prijava korisnika.
    Zaštićeno od brute-force napada: 5 neuspjelih pokušaja → 15 min blokada po IP-u.
    """
    client_ip = _get_client_ip(request)

    # Provjeri je li IP blokiran
    blocked, retry_after = login_rate_limiter.is_blocked(client_ip)
    if blocked:
        minutes = retry_after // 60
        seconds = retry_after % 60
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Previše neuspjelih pokušaja prijave. "
                f"Pokušajte ponovo za {minutes}m {seconds}s."
            ),
            headers={"Retry-After": str(retry_after)},
        )

    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        just_blocked, block_secs = login_rate_limiter.record_failure(client_ip)
        if just_blocked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Previše neuspjelih pokušaja prijave. "
                    f"Pokušajte ponovo za {block_secs // 60} minuta."
                ),
                headers={"Retry-After": str(block_secs)},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Pogrešno korisničko ime ili lozinka"
        )

    # Uspješna prijava – resetiraj brojač
    login_rate_limiter.record_success(client_ip)

    library_name = None
    if user.library_id:
        lib = db.query(Library).filter(Library.id == user.library_id).first()
        library_name = lib.name if lib else None

    token = create_access_token({
        "sub": user.username,
        "role": user.role,
        "library_id": user.library_id,
    })
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "full_name": user.full_name or user.username,
        "library_id": user.library_id,
        "library_name": library_name,
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return _user_to_out(current_user, show_password=False)


@router.post("/refresh", response_model=Token)
async def refresh_token(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    library_name = None
    if current_user.library_id:
        lib = db.query(Library).filter(Library.id == current_user.library_id).first()
        library_name = lib.name if lib else None

    new_token = create_access_token({
        "sub": current_user.username,
        "role": current_user.role,
        "library_id": current_user.library_id,
    })
    return {
        "access_token": new_token,
        "token_type": "bearer",
        "role": current_user.role,
        "full_name": current_user.full_name or current_user.username,
        "library_id": current_user.library_id,
        "library_name": library_name,
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.get("/users")
async def get_users(
    current_user: User = Depends(require_admin),
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    """
    Dohvati korisnike.
    - Super admin (library_id=None): vidi sve korisnike, sve dekriptirane lozinke
    - Library admin (library_id=X):  vidi samo svoju knjižnicu, dekriptirane lozinke
    """
    q = db.query(User)
    if library_id is not None:
        q = q.filter(User.library_id == library_id)
    users = q.all()

    show_pw = _can_see_passwords(current_user)
    return [_user_to_out(u, show_password=show_pw) for u in users]


@router.post("/users", status_code=201)
async def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Korisničko ime već postoji")

    # Library admin može kreirati korisnike samo za svoju knjižnicu
    lib_id = data.library_id
    if current_user.library_id is not None:
        lib_id = current_user.library_id

    user = User(
        username=data.username,
        full_name=data.full_name,
        email=data.email,
        role=data.role,
        library_id=lib_id,
        hashed_password=hash_password(data.password),
        plain_password=encrypt_password(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return _user_to_out(user, show_password=_can_see_passwords(current_user))


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    data: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Korisnik nije pronađen")

    # Library admin ne može editirati korisnike druge knjižnice
    if current_user.library_id and user.library_id != current_user.library_id:
        raise HTTPException(status_code=403, detail="Pristup odbijen")

    if data.username != user.username and db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Korisničko ime već postoji")

    user.username  = data.username
    user.full_name = data.full_name
    user.email     = data.email
    user.role      = data.role

    # library_id: admin može promijeniti SAMO unutar svoje knjižnice ili je globalni admin
    if data.library_id is not None:
        if current_user.library_id and data.library_id != current_user.library_id:
            raise HTTPException(
                status_code=403,
                detail="Možete uređivati samo korisnike unutar vlastite knjižnice."
            )
    user.library_id = data.library_id

    if data.password:
        user.hashed_password = hash_password(data.password)
        user.plain_password  = encrypt_password(data.password)

    db.commit()
    db.refresh(user)

    return _user_to_out(user, show_password=_can_see_passwords(current_user))


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current=Depends(require_admin)
):
    if current.id == user_id:
        raise HTTPException(status_code=400, detail="Ne možete obrisati sami sebe")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Korisnik nije pronađen")
    if current.library_id and user.library_id != current.library_id:
        raise HTTPException(status_code=403, detail="Pristup odbijen")
    db.delete(user)
    db.commit()


@router.post("/change-password")
async def change_password(
    data: PasswordChange,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user)
):
    from app.auth import verify_password
    if not verify_password(data.old_password, current.hashed_password):
        raise HTTPException(status_code=400, detail="Stara lozinka nije ispravna")
    current.hashed_password = hash_password(data.new_password)
    current.plain_password = encrypt_password(data.new_password)
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
    from app.models.models import Member
    q = db.query(Member).filter(
        Member.member_number == data.member_number,
        Member.is_active == True
    )
    if current_user.library_id:
        q = q.filter(Member.library_id == current_user.library_id)
    member = q.first()
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
