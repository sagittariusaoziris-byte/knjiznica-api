from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base, SessionLocal
from app.routes import books, members, loans, reservations
from app.routes import auth as auth_router
from app.routes import sync as sync_router
from app.routes import recommendations as rec_router

from app.models import recommendations  # noqa
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Knjižnica API",
    description="REST API za upravljanje knjižnicom — knjige, članovi, posudbe i rezervacije.",
    version="2.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(books.router)
app.include_router(members.router)
app.include_router(loans.router)
app.include_router(reservations.router)
app.include_router(sync_router.router)
app.include_router(rec_router.router)


@app.on_event("startup")
def create_default_admin():
    db = SessionLocal()
    try:
        from app.models.user import User, UserRole
        from app.auth import hash_password
        if db.query(User).count() == 0:
            admin = User(
                username="admin",
                full_name="Administrator",
                role=UserRole.admin,
                hashed_password=hash_password("admin123"),
                plain_password="admin123",
                is_active=True
            )
            db.add(admin)
            db.commit()
            print("✓ Default admin kreiran: admin / admin123")
    finally:
        db.close()


@app.get("/", tags=["Status"])
def root():
    return {"status": "ok", "poruka": "Knjižnica API v2.1 radi ✓"}


@app.get("/stats", tags=["Status"])
def get_stats():
    from app.models.models import Book, Member, Loan
    from datetime import date
    db = SessionLocal()
    try:
        return {
            "ukupno_knjiga": db.query(Book).count(),
            "ukupno_clanova": db.query(Member).filter(Member.is_active == True).count(),
            "aktivne_posudbe": db.query(Loan).filter(Loan.is_returned == False).count(),
            "prekoracene_posudbe": db.query(Loan).filter(
                Loan.is_returned == False,
                Loan.due_date < date.today()
            ).count(),
        }
    finally:
        db.close()
