"""
app/main.py
VERZIJA: 9.0.0 — Multi-tenant (Opcija A, library_id)

IZMJENE:
  - Registriran libraries_router (admin upravljanje knjižnicama)
  - Startup seed: 4 knjižnice + admin korisnici po knjižnici
  - library_id u JWT tokenu za sve korisnike
  - NOVO: pdf_router za server-side PDF generiranje
"""
from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from app.database import Base, SessionLocal, engine

# ── Importi modela da SQLAlchemy registrira tablice ───────────────────────────
from app.models.library       import Library         # noqa — NOVO: libraries tablica
from app.models               import recommendations # noqa
from app.models.notification  import Notification    # noqa
from app.models.license_record import LicenseRecord  # noqa
from app.models.user          import User, UserRole  # noqa
from app.models.models        import Book, Member, Loan, Reservation, Rating  # noqa

# ── Routeri ───────────────────────────────────────────────────────────────────
from app.routes import auth          as auth_router
from app.routes import books
from app.routes import calendar      as calendar_router
from app.routes import chat_router   as chat_ws_router
from app.routes import images        as images_router
from app.routes import license       as license_router
from app.routes import libraries     as libraries_router   # NOVO
from app.routes import loans, members
from app.routes import notifications as notifications_router
from app.routes import online_users  as online_users_router
from app.routes import pdf           as pdf_router         # NOVO: PDF ispisi
from app.routes import backup        as backup_router      # NOVO: Backup/restore
from app.routes import ratings       as ratings_router
from app.routes import recommendations as rec_router
from app.routes import reservations
from app.routes import server_books  as server_books_router
from app.routes import stats         as stats_router
from app.routes import sync          as sync_router
from app.routes import websocket_router as ws_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

Base.metadata.create_all(bind=engine)


# ── Auto-migrate: dodaj nove kolone ako nedostaju (v8.6.0) ───────────────────
def _auto_migrate_licenses():
    """Dodaj nove kolone u licenses tablicu ako ne postoje (sigurno)."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    if "licenses" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("licenses")}
    new_cols = {
        "hostname":         "ALTER TABLE licenses ADD COLUMN hostname VARCHAR",
        "os_platform":      "ALTER TABLE licenses ADD COLUMN os_platform VARCHAR",
        "os_version":       "ALTER TABLE licenses ADD COLUMN os_version VARCHAR",
        "app_version":      "ALTER TABLE licenses ADD COLUMN app_version VARCHAR",
        "activation_count": "ALTER TABLE licenses ADD COLUMN activation_count INTEGER DEFAULT 0",
        "last_seen":        "ALTER TABLE licenses ADD COLUMN last_seen TIMESTAMP",
        "activated_at":     "ALTER TABLE licenses ADD COLUMN activated_at TIMESTAMP",
        "notes":            "ALTER TABLE licenses ADD COLUMN notes TEXT",
        "mid_reset_count":  "ALTER TABLE licenses ADD COLUMN mid_reset_count INTEGER DEFAULT 0",
    }
    with engine.connect() as conn:
        for col, sql in new_cols.items():
            if col not in existing:
                try:
                    conn.execute(text(sql))
                    conn.commit()
                except Exception:
                    pass


def _seed_libraries_and_users(db):
    """Kreiraj 4 knjižnice i admin+knjiznicar korisnike za svaku."""
    from app.auth import hash_password

    libraries_data = [
        {"id": 1, "name": "Knjižnica Bugojno",  "slug": "bugojno",  "city": "Bugojno"},
        {"id": 2, "name": "Knjižnica Sarajevo", "slug": "sarajevo", "city": "Sarajevo"},
        {"id": 3, "name": "Knjižnica Mostar",   "slug": "mostar",   "city": "Mostar"},
        {"id": 4, "name": "Knjižnica Zenica",   "slug": "zenica",   "city": "Zenica"},
    ]

    for ld in libraries_data:
        if not db.query(Library).filter(Library.id == ld["id"]).first():
            db.add(Library(**ld))

    db.commit()

    # Globalni admin (bez library_id — vidi sve)
    if not db.query(User).filter(User.username == "admin").first():
        db.add(User(
            username="admin", full_name="Globalni Administrator",
            role=UserRole.admin, library_id=None,
            hashed_password=hash_password("admin123"),
            plain_password="admin123", is_active=True,
        ))

    # Admin i knjižničar za svaku knjižnicu
    user_seeds = [
        # (username,         full_name,              role,                 lib_id, password)
        ("admin_bugojno",   "Admin Bugojno",   UserRole.admin,      1, "bugojno123"),
        ("knjiz_bugojno",   "Knjižničar Bugojno",  UserRole.knjiznicar, 1, "bugojno123"),
        ("admin_sarajevo",  "Admin Sarajevo",  UserRole.admin,      2, "sarajevo123"),
        ("knjiz_sarajevo",  "Knjižničar Sarajevo", UserRole.knjiznicar, 2, "sarajevo123"),
        ("admin_mostar",    "Admin Mostar",    UserRole.admin,      3, "mostar123"),
        ("knjiz_mostar",    "Knjižničar Mostar",   UserRole.knjiznicar, 3, "mostar123"),
        ("admin_zenica",    "Admin Zenica",    UserRole.admin,      4, "zenica123"),
        ("knjiz_zenica",    "Knjižničar Zenica",   UserRole.knjiznicar, 4, "zenica123"),
    ]

    for uname, fname, role, lib_id, pwd in user_seeds:
        if not db.query(User).filter(User.username == uname).first():
            db.add(User(
                username=uname, full_name=fname, role=role,
                library_id=lib_id,
                hashed_password=hash_password(pwd),
                plain_password=pwd, is_active=True,
            ))

    db.commit()
    print("✓ Knjižnice i korisnici inicijalizirani (v9.0.0)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _auto_migrate_licenses()
    db = SessionLocal()
    try:
        _seed_libraries_and_users(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Knjižnica API",
    description="REST API za upravljanje knjižnicom — multi-tenant (Opcija A)",
    version="9.0.0",
    lifespan=lifespan,
)

APP_VERSION = "v9.0.0"

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000", "http://localhost:3000", "http://localhost:8080",
        "http://127.0.0.1:8000", "http://127.0.0.1:3000",
        "https://knjiznica-api.onrender.com",
        "http://localhost:5000", "http://10.0.2.2:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Registracija routera ──────────────────────────────────────────────────────
app.include_router(auth_router.router)
app.include_router(libraries_router.router)   # NOVO: /libraries/
app.include_router(books.router)
app.include_router(members.router)
app.include_router(loans.router)
app.include_router(reservations.router)
app.include_router(sync_router.router)
app.include_router(rec_router.router)
app.include_router(notifications_router.router)
app.include_router(ratings_router.router)
app.include_router(ws_router.router)
app.include_router(chat_ws_router.router)
app.include_router(online_users_router.router)
app.include_router(calendar_router.router)
app.include_router(images_router.router)
app.include_router(server_books_router.router)
app.include_router(stats_router.router)
app.include_router(pdf_router.router)         # NOVO: /pdf/
app.include_router(backup_router.router)      # NOVO: /backup/
app.include_router(license_router.router)


@app.get("/", tags=["Status"])
def root():
    return {"status": "ok", "verzija": APP_VERSION,
            "poruka": f"Knjižnica API {APP_VERSION} — Multi-tenant ✓"}


@app.get("/status", tags=["Status"])
def get_status():
    from datetime import date
    db = SessionLocal()
    try:
        return {
            "ukupno_knjiga":     db.query(Book).count(),
            "ukupno_clanova":    db.query(Member).filter(Member.is_active == True).count(),
            "aktivne_posudbe":   db.query(Loan).filter(Loan.is_returned == False).count(),
            "prekoracene_posudbe": db.query(Loan).filter(
                Loan.is_returned == False, Loan.due_date < date.today()).count(),
            "verzija": APP_VERSION,
            "knjiznice": db.query(Library).count(),
        }
    finally:
        db.close()
