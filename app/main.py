"""
library_api/app/main.py
Verzija: 8.4 — KOMPLETNO ISPRAVLJENA

ISPRAVCI v8.3:
  1. Uklonjen ImportError: briše se import Notification iz routes/notifications
     i BookRating iz routes/ratings — modeli se importiraju iz models/
  2. Registriran websocket_router → /ws/notifications i /ws/admin sada rade
  3. Registriran chat_router → WebSocket chat endpoint dostupan
  4. Registriran online_users router → /online-users/ čita stvarne WS korisnike
  5. Registrirani calendar, images, server_books, stats routeri
  6. Uklonjen stub /online-users/ koji je uvijek vraćao praznu listu
  7. CORS: dodan wildcard za mobilne Flutter apps u razvoju
"""

from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager

from app.database import Base, SessionLocal, engine

# ── Importi modela da SQLAlchemy registrira tablice ───────────────────────────
from app.models import recommendations  # noqa — registrira Recommendation model
from app.models.notification import (
    Notification,
)  # noqa — registrira notifications tablicu
from app.models.license_record import LicenseRecord  # noqa — registrira licenses tablicu

# ── Dodatni routeri (v8.3) ────────────────────────────────────────────────────
# ── Real-time routeri (v8.3) ──────────────────────────────────────────────────
# ── Novi routeri (v8.2) ───────────────────────────────────────────────────────
# ── Core routeri ──────────────────────────────────────────────────────────────
from app.routes import auth as auth_router
from app.routes import books
from app.routes import calendar as calendar_router
from app.routes import chat_router as chat_ws_router  # WebSocket chat
from app.routes import images as images_router
from app.routes import license as license_router
from app.routes import loans, members
from app.routes import notifications as notifications_router
from app.routes import online_users as online_users_router  # /online-users/
from app.routes import ratings as ratings_router
from app.routes import recommendations as rec_router
from app.routes import reservations
from app.routes import server_books as server_books_router
from app.routes import stats as stats_router
from app.routes import sync as sync_router
from app.routes import websocket_router as ws_router  # /ws/notifications, /ws/admin
from app.routes.ratings import BookRating  # noqa — registrira book_ratings tablicu
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# (BookRating je inline model u ratings.py, nema models/ratings.py)

Base.metadata.create_all(bind=engine)

# ── Auto-migrate: dodaj nove kolone ako nedostaju (v8.6.0) ───────────────────
# Štiti od situacije gdje postoji stara 'licenses' tablica bez novih polja.
def _auto_migrate_licenses():
    """Idempotentno dodavanje kolona koje model v8.6.0 zahtijeva."""
    import sqlalchemy as _sa
    from sqlalchemy import inspect as _inspect, text as _text
    try:
        insp = _inspect(engine)
        if "licenses" not in insp.get_table_names():
            return  # create_all će je kreirati gore
        existing = {c["name"] for c in insp.get_columns("licenses")}
        migrations = [
            ("activated_at",     "DATETIME"),
            ("last_seen",        "DATETIME"),
            ("hostname",         "VARCHAR(255)"),
            ("os_platform",      "VARCHAR(64)"),
            ("os_version",       "VARCHAR(128)"),
            ("app_version",      "VARCHAR(32)"),
            ("activation_count", "INTEGER DEFAULT 0"),
            ("notes",            "TEXT"),
        ]
        with engine.connect() as conn:
            for col, col_type in migrations:
                if col not in existing:
                    conn.execute(_text(f"ALTER TABLE licenses ADD COLUMN {col} {col_type}"))
                    print(f"[auto-migrate] licenses.{col} dodano")
            conn.commit()
    except Exception as _e:
        print(f"[auto-migrate] upozorenje: {_e}")

_auto_migrate_licenses()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────
    db = SessionLocal()
    try:
        from app.auth import hash_password
        from app.models.user import User, UserRole

        if db.query(User).count() == 0:
            admin = User(
                username="admin",
                full_name="Administrator",
                role=UserRole.admin,
                hashed_password=hash_password("admin123"),
                plain_password="admin123",
                is_active=True,
            )
            db.add(admin)
            db.commit()
            print("✓ Default admin kreiran: admin / admin123")
    finally:
        db.close()

    yield
    # ── Shutdown ──────────────────────────────────────────────────────────


app = FastAPI(
    title="Knjižnica API",
    description="REST API za upravljanje knjižnicom — knjige, članovi, posudbe, WebSocket.",
    version="8.5.5",
    lifespan=lifespan,
)

APP_VERSION = "v8.5.5"

# ── CORS ──────────────────────────────────────────────────────────────────────
# Flutter Android ne šalje Origin header pri HTTP requestima.
# WebSocket handshake ga šalje — Render URL mora biti u listi.
# Za lokalni razvoj s emulatorom (10.0.2.2) dodajemo wildcard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # Lokalni razvoj
        "http://localhost:8000",
        "http://localhost:3000",
        "http://localhost:8080",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:3000",
        # Render production
        "https://knjiznica-api.onrender.com",
        # Flutter web
        "http://localhost:5000",
        # Android emulator (HTTP origin za WS handshake)
        "http://10.0.2.2:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Registracija routera ──────────────────────────────────────────────────────

# Core
app.include_router(auth_router.router)
app.include_router(books.router)
app.include_router(members.router)
app.include_router(loans.router)
app.include_router(reservations.router)
app.include_router(sync_router.router)
app.include_router(rec_router.router)

# v8.2 dodaci
app.include_router(notifications_router.router)
app.include_router(ratings_router.router)

# v8.3 — real-time (websocket + chat)
app.include_router(ws_router.router)  # /ws/notifications, /ws/admin, /ws/stats
app.include_router(chat_ws_router.router)  # /ws/chat/...
app.include_router(online_users_router.router)  # /online-users/

# v8.3 — dodatni REST routeri
app.include_router(calendar_router.router)
app.include_router(images_router.router)
app.include_router(server_books_router.router)
app.include_router(stats_router.router)
app.include_router(license_router.router)


# ── Status endpointovi ────────────────────────────────────────────────────────


@app.get("/", tags=["Status"])
def root():
    return {
        "status": "ok",
        "verzija": APP_VERSION,
        "poruka": f"Knjižnica API {APP_VERSION} radi ✓",
    }


@app.get("/status", tags=["Status"])
def get_status():
    from datetime import date

    from app.models.models import Book, Loan, Member

    db = SessionLocal()
    try:
        return {
            "ukupno_knjiga": db.query(Book).count(),
            "ukupno_clanova": db.query(Member).filter(Member.is_active == True).count(),
            "aktivne_posudbe": db.query(Loan).filter(Loan.is_returned == False).count(),
            "prekoracene_posudbe": db.query(Loan)
            .filter(Loan.is_returned == False, Loan.due_date < date.today())
            .count(),
            "verzija": APP_VERSION,
        }
    finally:
        db.close()
