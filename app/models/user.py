import enum

from app.database import Base
from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func


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

    # Relationships
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
