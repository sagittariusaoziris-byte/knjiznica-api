from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum
from sqlalchemy.sql import func
from app.database import Base
import enum


class UserRole(str, enum.Enum):
    admin = "admin"
    knjiznicar = "knjiznicar"
    citac = "citac"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    email = Column(String, unique=True, nullable=True)
    hashed_password = Column(String, nullable=False)
    plain_password = Column(String, nullable=True)  # Vidljivo samo adminu
    role = Column(Enum(UserRole), default=UserRole.knjiznicar, nullable=False)
    is_active = Column(Boolean, default=True)
    member_id = Column(Integer, nullable=True)  # Povezani clan
    created_at = Column(DateTime(timezone=True), server_default=func.now())
