"""
app/auth.py
VERZIJA: 9.0.0 — library_id u JWT tokenu

IZMJENE:
  - create_access_token uključuje library_id
  - get_current_user vraća library_id iz tokena
  - get_library_id(user) — centralni dependency za sve routere
  - Globalni admin (library_id=None) može pristupiti svemu
"""
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError, jwt
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

_DEFAULT_SECRET = "knjiznica-super-tajni-kljuc-2024-promijeniti-u-produkciji"
SECRET_KEY = os.environ.get("KNJIZNICA_SECRET_KEY", _DEFAULT_SECRET)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 sati

if SECRET_KEY == _DEFAULT_SECRET:
    logger.warning(
        "⚠️  SIGURNOSNO UPOZORENJE: KNJIZNICA_SECRET_KEY nije postavljen! "
        "Koristite Render Dashboard → Environment Variables."
    )

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


# ── LOZINKE ───────────────────────────────────────────────────────────────────

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# ── JWT TOKENI ────────────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# ── KORISNICI ─────────────────────────────────────────────────────────────────

def get_user(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = get_user(db, username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


# ── DEPENDENCY INJECTIONS ─────────────────────────────────────────────────────

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Nevažeći token – prijavite se ponovno",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token je istekao – prijavite se ponovno",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError:
        raise credentials_exception

    user = get_user(db, username)
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Korisnički račun je deaktiviran",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_library_id(current_user: User = Depends(get_current_user)) -> Optional[int]:
    """
    Centralni dependency za dohvat library_id iz JWT-a.
    - Globalni admin (library_id=None) vraća None → rute ga tretiraju kao "vidi sve"
    - Svi ostali vraćaju svoju knjižnicu
    """
    return current_user.library_id


def require_role(*roles: UserRole):
    async def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            role_names = ", ".join(r.value for r in roles)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Pristup odbijen. Potrebna uloga: {role_names}",
            )
        return current_user
    return checker


require_admin = require_role(UserRole.admin)
require_staff  = require_role(UserRole.admin, UserRole.knjiznicar)
require_any    = require_role(UserRole.admin, UserRole.knjiznicar, UserRole.citac)
