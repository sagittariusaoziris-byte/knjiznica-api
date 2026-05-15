"""
app/main.py
VERZIJA: 9.4.7 — Multi-tenant + Alembic migracije + Paginacija

IZMJENE vs 9.4.6:
  - Seed INSERT ONLY za knjižnice — ručne izmjene naziva/sluga/grada ostaju sačuvane
  - Seed INSERT ONLY za korisnike — postojeći korisnici se nikad ne diraju
  - Sync /export, /import i /status uključuju libraries[] tablicu
  - update_user endpoint prihvaća i ažurira library_id (s sigurnosnom provjerom)
  - UserDialog u tab_users.py sada ima dropdown za odabir knjižnice
"""
from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager

# ── Importi modela da SQLAlchemy registrira tablice (potrebno za Alembic) ────
from app.models.library       import Library         # noqa
from app.models               import recommendations # noqa
from app.models.notification  import Notification    # noqa
from app.models.license_record import LicenseRecord  # noqa
from app.models.user          import User, UserRole  # noqa
from app.models.models        import Book, Member, Loan, Reservation, Rating  # noqa
from app.models.book_rating   import BookRating      # noqa

from app.database import Base, SessionLocal, engine, get_db
from app.auth import get_library_id
from typing import Optional
from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

# ── Routeri ───────────────────────────────────────────────────────────────────
from app.routes import auth          as auth_router
from app.routes import books
from app.routes import calendar      as calendar_router
from app.routes import chat_router   as chat_ws_router
from app.routes import images        as images_router
from app.routes import license       as license_router
from app.routes import libraries     as libraries_router
from app.routes import loans, members
from app.routes import notifications as notifications_router
from app.routes import online_users  as online_users_router
from app.routes import pdf           as pdf_router
from app.routes import backup        as backup_router
from app.routes import super_admin   as super_admin_router
from app.routes import ratings       as ratings_router
from app.routes import recommendations as rec_router
from app.routes import reservations
# server_books uklonjen — duplikat books.py
from app.routes import stats         as stats_router
from app.routes import sync          as sync_router
from app.routes import websocket_router as ws_router
from fastapi.middleware.cors import CORSMiddleware


def _run_alembic_migrations():
    """
    Pokreni sve pending Alembic migracije pri startu servera.
    Ako baza već postoji (kreirana kroz create_all), stampa head
    bez pokretanja migracija — sprječava grešku 'table already exists'.
    """
    try:
        from alembic.config import Config
        from alembic import command
        from alembic.runtime.migration import MigrationContext
        import os

        # Traži alembic.ini u root direktoriju projekta
        alembic_cfg_path = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
        alembic_cfg_path = os.path.abspath(alembic_cfg_path)

        if not os.path.exists(alembic_cfg_path):
            print(f"⚠ alembic.ini nije pronađen na {alembic_cfg_path} — preskačem migracije")
            Base.metadata.create_all(bind=engine)
            return

        cfg = Config(alembic_cfg_path)
        db_url = str(engine.url)
        cfg.set_main_option("sqlalchemy.url", db_url)

        # Provjeri trenutni alembic_version u bazi
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            current_rev = ctx.get_current_revision()

        if current_rev is None:
            # Baza postoji ali Alembic je nikad nije vidio →
            # Provjeri je li schema POTPUNO kreirana (libraries + users moraju postojati)
            with engine.connect() as check_conn:
                has_libraries = engine.dialect.has_table(check_conn, "libraries")
                has_users = engine.dialect.has_table(check_conn, "users")

            if has_libraries and has_users:
                # Stara baza bez alembic_version — stamp da se izbjegne re-run
                print("⚠ Baza postoji bez alembic_version — stampam head (bez migracija)")
                command.stamp(cfg, "head")
                print("✓ Alembic stamp head završen")
                return
            # Inače: nova/nepotpuna baza → pokreni sve migracije

        command.upgrade(cfg, "head")
        print("✓ Alembic migracije primijenjene (upgrade head)")

    except Exception as e:
        print(f"⚠ Alembic greška: {e}")
        print("  Fallback: Base.metadata.create_all()")
        Base.metadata.create_all(bind=engine)


def _seed_libraries_and_users(db):
    """
    Inicijalizacija knjižnica i zadanih korisnika.

    Knjižnice — INSERT ONLY: kreira samo ako ne postoji, nikad ne prepisuje.
    Korisnici  — INSERT ONLY: postojeći korisnici se nikad ne diraju
                 (promjene lozinki/emailova ostaju sačuvane).
    """
    from app.auth import hash_password

    # ── Stvarne knjižnice (usklađeno sa Supabase bazom) ──────────────────────
    libraries_data = [
        {"id": 1, "name": "Knjižnica Srednje škole Uskoplje", "slug": "ssu",    "city": "Uskoplje"},
        {"id": 2, "name": "Knjižnica Osnovna škola Uskoplje",  "slug": "osu",    "city": "Uskoplje"},
        {"id": 3, "name": "Napretkova knjižnica",              "slug": "hkd",    "city": "Uskoplje"},
        {"id": 4, "name": "Knjižnica Zenica",                  "slug": "zenica", "city": "Zenica"},
    ]

    # INSERT ONLY: kreira knjižnicu samo ako ne postoji.
    # Nikad ne prepisuje ručne izmjene naziva/sluga/grada iz Super Admin panela.
    for ld in libraries_data:
        if not db.query(Library).filter(Library.id == ld["id"]).first():
            db.add(Library(**ld))

    db.commit()

    # ── Globalni super-admin (bez library_id — vidi sve knjižnice) ────────────
    if not db.query(User).filter(User.username == "admin").first():
        db.add(User(
            username="admin", full_name="Globalni Administrator",
            role=UserRole.admin, library_id=None,
            hashed_password=hash_password("admin123"),
            plain_password="admin123", is_active=True,
        ))

    # ── Zadani korisnici po knjižnici — INSERT ONLY (ne mijenja postojeće) ───
    # Usernames odgovaraju stvarnim knjižnicama:
    #   ssu = Srednja škola Uskoplje  (id=1)
    #   osu = Osnovna škola Uskoplje  (id=2)
    #   hkd = Napretkova knjižnica    (id=3)
    #   zenica = Knjižnica Zenica     (id=4)
    user_seeds = [
        ("admin_ssu",    "Admin SŠU",               UserRole.admin,      1, "sšuskoplje"),
        ("knjiz_ssu",    "Knjižničar SŠU",           UserRole.knjiznicar, 1, "knjiznicar"),
        ("admin_osu",    "Admin OŠU",               UserRole.admin,      2, "adminvgmail.com"),
        ("knjiz_osu",    "Knjižničar OŠU",          UserRole.knjiznicar, 2, "knjiz123"),
        ("admin_hkd",    "Admin Napredak",           UserRole.admin,      3, "hkd123"),
        ("knjiz_hkd",    "Knjižničar Napredak",      UserRole.knjiznicar, 3, "knjiz123"),
        ("admin_zenica", "Admin Zenica",             UserRole.admin,      4, "zenica123"),
        ("knjiz_zenica", "Knjižničar Zenica",        UserRole.knjiznicar, 4, "zenica123"),
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
    print("✓ Knjižnice i korisnici inicijalizirani (v9.4.6)")


def _startup_init():
    """Pokreće migracije i seed u pozadini — ne blokira port binding."""
    import time, traceback
    time.sleep(1)
    try:
        _run_alembic_migrations()
    except Exception as e:
        print(f"❌ STARTUP MIGRATION ERROR: {e}")
        traceback.print_exc()
        return
    db = SessionLocal()
    try:
        _seed_libraries_and_users(db)
        print("✓ Startup završen — migracije i seed OK")
    except Exception as e:
        print(f"❌ STARTUP SEED ERROR: {e}")
        traceback.print_exc()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Background thread — uvicorn odmah veže port, Render ne timeout-a
    import threading
    t = threading.Thread(target=_startup_init, daemon=True)
    t.start()
    yield
    t.join(timeout=10)


app = FastAPI(
    title="Knjižnica API",
    description="REST API za upravljanje knjižnicom — multi-tenant (Opcija A) + Super Admin Panel",
    version="9.4.6",
    lifespan=lifespan,
)

APP_VERSION = "v9.4.6"

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
app.include_router(libraries_router.router)
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
# app.include_router(server_books_router.router)  # uklonjen duplikat
app.include_router(stats_router.router)
app.include_router(pdf_router.router)
app.include_router(backup_router.router)
app.include_router(license_router.router)
app.include_router(super_admin_router.router)


@app.get("/", tags=["Status"])
def root():
    return {"status": "ok", "verzija": APP_VERSION,
            "poruka": f"Knjižnica API {APP_VERSION} — Multi-tenant ✓ Alembic ✓ Paginacija ✓"}


@app.get("/status", tags=["Status"])
def get_status(
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db),
):
    from datetime import date
    q_books   = db.query(Book)
    q_members = db.query(Member).filter(Member.is_active == True)
    q_active  = db.query(Loan).filter(Loan.is_returned == False)
    q_overdue = db.query(Loan).filter(Loan.is_returned == False, Loan.due_date < date.today())

    if library_id is not None:
        # Admin knjižnice — vidi samo svoju knjižnicu
        q_books   = q_books.filter(Book.library_id == library_id)
        q_members = q_members.filter(Member.library_id == library_id)
        q_active  = q_active.filter(Loan.library_id == library_id)
        q_overdue = q_overdue.filter(Loan.library_id == library_id)
    # super_admin (library_id=None) → vidi zbroj svih knjižnica

    return {
        "ukupno_knjiga":       q_books.count(),
        "ukupno_clanova":      q_members.count(),
        "aktivne_posudbe":     q_active.count(),
        "prekoracene_posudbe": q_overdue.count(),
        "verzija": APP_VERSION,
        "knjiznice": db.query(Library).count(),
    }
