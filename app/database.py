import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Koristi DATABASE_URL environment varijablu (Supabase PostgreSQL)
# Ako nije postavljena, koristi lokalni SQLite kao fallback
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./library.db")

# PostgreSQL ispravka za SQLAlchemy (postgres:// → postgresql://)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Konfiguracija enginea
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
else:
    # Supabase PgBouncer kompatibilnost — isključi prepared statements
    connect_args = {}
    if "pgbouncer=true" in DATABASE_URL or "pooler.supabase.com" in DATABASE_URL:
        connect_args = {"options": "-c statement_timeout=30000"}
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        max_overflow=10,
        connect_args=connect_args,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
