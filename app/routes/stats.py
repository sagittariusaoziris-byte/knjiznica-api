"""
Stats routes for Knjižnica API
Statistički endpointi za analitiku knjižnice.
"""

from datetime import date, datetime, timedelta
from typing import Optional

from app.database import get_db
from app.models.models import Book, Loan, Member, Rating
from app.websocket import notify_stats_updated
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import case, extract, func, literal
from sqlalchemy.orm import Session

router = APIRouter(prefix="/stats", tags=["Statistike"])

# FIX v8.5.6: Dodana root ruta za kompatibilnost s Flutter aplikacijom
@router.get("/")
def get_stats_root(db: Session = Depends(get_db)):
    """Vraća sažetak statistika (poziva summary)."""
    return get_library_summary(db)


@router.get("/popular-books")
def get_popular_books(
    limit: Optional[int] = Query(10, ge=1, le=100, description="Broj rezultata"),
    db: Session = Depends(get_db),
):
    """
    Najčitanije knjige (po broju posudbi).

    - **limit**: Broj rezultata (1-100)
    """
    loan_count_subq = (
        db.query(Loan.book_id, func.count(Loan.id).label("loan_count"))
        .group_by(Loan.book_id)
        .subquery()
    )

    books = (
        db.query(Book, loan_count_subq.c.loan_count)
        .join(loan_count_subq, Book.id == loan_count_subq.c.book_id)
        .order_by(loan_count_subq.c.loan_count.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": book.id,
            "title": book.title,
            "author": book.author,
            "isbn": book.isbn,
            "genre": book.genre,
            "shelf": book.shelf,
            "loan_count": count,
        }
        for book, count in books
    ]


@router.get("/active-members")
def get_active_members(
    limit: Optional[int] = Query(10, ge=1, le=100, description="Broj rezultata"),
    db: Session = Depends(get_db),
):
    """
    Najaktivniji članovi (po broju posudbi).

    - **limit**: Broj rezultata (1-100)
    """
    loan_count_subq = (
        db.query(Loan.member_id, func.count(Loan.id).label("loan_count"))
        .group_by(Loan.member_id)
        .subquery()
    )

    members = (
        db.query(Member, loan_count_subq.c.loan_count)
        .join(loan_count_subq, Member.id == loan_count_subq.c.member_id)
        .order_by(loan_count_subq.c.loan_count.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": member.id,
            "member_number": member.member_number,
            "first_name": member.first_name,
            "last_name": member.last_name,
            "email": member.email,
            "loan_count": count,
        }
        for member, count in members
    ]


@router.get("/loans-by-month")
def get_loans_by_month(
    year: Optional[int] = Query(
        None, description="Godina (ako nije navedeno, trenutna)"
    ),
    db: Session = Depends(get_db),
):
    """
    Trend posudbi po mjesecima.

    - **year**: Godina za analizu (default: trenutna godina)
    """
    if not year:
        year = datetime.now().year

    loans_by_month = (
        db.query(
            extract("month", Loan.loan_date).label("month"),
            func.count(Loan.id).label("count"),
        )
        .filter(extract("year", Loan.loan_date) == year)
        .group_by(extract("month", Loan.loan_date))
        .order_by(extract("month", Loan.loan_date))
        .all()
    )

    # Popuni sve mjesece (čak i one bez posudbi)
    result = []
    for month_num in range(1, 13):
        count = next((c for m, c in loans_by_month if int(m) == month_num), 0)
        result.append(
            {
                "month": month_num,
                "month_name": date(2000, month_num, 1).strftime("%B"),
                "count": count,
            }
        )

    return {
        "year": year,
        "monthly_loans": result,
        "total_loans": sum(item["count"] for item in result),
    }


@router.get("/overdue-analysis")
def get_overdue_analysis(db: Session = Depends(get_db)):
    """
    Analiza kašnjenja.

    Prikazuje ukupan broj kašnjenja i raspodjelu po danima kašnjenja.
    """
    today = date.today()

    # Ukupno aktivnih kašnjenja
    total_overdue = (
        db.query(Loan).filter(Loan.is_returned == False, Loan.due_date < today).count()
    )

    # Kašnjenja po danima (grupirano po broju dana kašnjenja)
    overdue_loans = (
        db.query(Loan).filter(Loan.is_returned == False, Loan.due_date < today).all()
    )

    # Izračunaj dane kašnjenja
    days_overdue_dict = {}
    for loan in overdue_loans:
        days = (today - loan.due_date).days
        days_overdue_dict[days] = days_overdue_dict.get(days, 0) + 1

    # Sortiraj po danima
    overdue_by_days = sorted(
        [
            {"days_overdue": days, "count": count}
            for days, count in days_overdue_dict.items()
        ],
        key=lambda x: x["days_overdue"],
        reverse=True,
    )

    # Kategoriziraj kašnjenja
    categories = {
        "1-7_dana": sum(
            1 for loan in overdue_loans if 1 <= (today - loan.due_date).days <= 7
        ),
        "8-30_dana": sum(
            1 for loan in overdue_loans if 8 <= (today - loan.due_date).days <= 30
        ),
        "31-90_dana": sum(
            1 for loan in overdue_loans if 31 <= (today - loan.due_date).days <= 90
        ),
        "90+_dana": sum(
            1 for loan in overdue_loans if (today - loan.due_date).days > 90
        ),
    }

    return {
        "total_overdue": total_overdue,
        "categories": categories,
        "overdue_by_days": overdue_by_days[:30],  # Top 30
        "analysis_date": today.isoformat(),
    }


@router.get("/shelf-occupancy")
def get_shelf_occupancy(db: Session = Depends(get_db)):
    """
    Popunjenost polica.

    Prikazuje koliko je knjiga na svakoj polici i kolika je popunjenost.
    """
    shelf_stats = (
        db.query(
            Book.shelf,
            func.count(Book.id).label("book_count"),
            func.sum(Book.total_copies).label("total_copies"),
            func.sum(Book.available_copies).label("available_copies"),
        )
        .group_by(Book.shelf)
        .order_by(func.count(Book.id).desc())
        .all()
    )

    result = []
    for shelf, count, total, available in shelf_stats:
        total = total or 0
        available = available or 0
        occupied = total - available
        occupancy_rate = round((occupied / total * 100), 2) if total > 0 else 0

        result.append(
            {
                "shelf": shelf or "Nedefinirano",
                "book_count": count,
                "total_copies": total,
                "available_copies": available,
                "occupied_copies": occupied,
                "occupancy_rate": occupancy_rate,
            }
        )

    # Ukupna statistika
    total_books = sum(item["book_count"] for item in result)
    total_copies = sum(item["total_copies"] for item in result)
    total_available = sum(item["available_copies"] for item in result)
    total_occupied = total_copies - total_available
    overall_occupancy = (
        round((total_occupied / total_copies * 100), 2) if total_copies > 0 else 0
    )

    return {
        "shelves": result,
        "summary": {
            "total_shelves": len(result),
            "total_books": total_books,
            "total_copies": total_copies,
            "total_available": total_available,
            "total_occupied": total_occupied,
            "overall_occupancy_rate": overall_occupancy,
        },
    }


@router.get("/summary")
def get_library_summary(db: Session = Depends(get_db)):
    """
    Sažetak stanja knjižnice.

    Brzi pregled ključnih statistika.
    """
    today = date.today()

    # Osnovne statistike
    total_books = db.query(Book).count()
    total_members = db.query(Member).count()
    active_members = db.query(Member).filter(Member.is_active == True).count()

    # Posudbe
    total_loans = db.query(Loan).count()
    active_loans = db.query(Loan).filter(Loan.is_returned == False).count()
    overdue_loans = (
        db.query(Loan).filter(Loan.is_returned == False, Loan.due_date < today).count()
    )

    # Posudbe ovaj mjesec
    current_month_loans = (
        db.query(Loan)
        .filter(
            extract("year", Loan.loan_date) == today.year,
            extract("month", Loan.loan_date) == today.month,
        )
        .count()
    )

    # Prosječna ocjena svih knjiga
    avg_rating_subq = db.query(func.avg(Rating.rating)).scalar()
    avg_rating = round(avg_rating_subq, 2) if avg_rating_subq else 0

    # Najpopularniji žanr
    genre_stats = (
        db.query(Book.genre, func.count(Book.id).label("count"))
        .filter(Book.genre != None)
        .group_by(Book.genre)
        .order_by(func.count(Book.id).desc())
        .first()
    )

    return {
        "books": {
            "total": total_books,
            "available_copies": db.query(func.sum(Book.available_copies)).scalar() or 0,
            "total_copies": db.query(func.sum(Book.total_copies)).scalar() or 0,
        },
        "members": {
            "total": total_members,
            "active": active_members,
            "inactive": total_members - active_members,
        },
        "loans": {
            "total": total_loans,
            "active": active_loans,
            "overdue": overdue_loans,
            "this_month": current_month_loans,
        },
        "ratings": {"average": avg_rating},
        "popular_genre": {
            "name": genre_stats[0] if genre_stats else None,
            "count": genre_stats[1] if genre_stats else 0,
        },
        "analysis_date": today.isoformat(),
    }


@router.get("/ratings-distribution")
def get_ratings_distribution(db: Session = Depends(get_db)):
    """
    Raspodjela ocjena knjiga.

    Prikazuje koliko knjiga ima koju prosječnu ocjenu.
    """
    # Izračunaj prosječne ocjene po knjigama
    avg_ratings = (
        db.query(
            Rating.book_id,
            func.avg(Rating.rating).label("avg_rating"),
            func.count(Rating.id).label("rating_count"),
        )
        .group_by(Rating.book_id)
        .having(func.count(Rating.id) >= 1)
        .subquery()
    )

    # Grupiraj po rasponima ocjena
    rating_ranges = [
        ("5_stars", 5.0, 5.0),
        ("4_stars", 4.0, 4.99),
        ("3_stars", 3.0, 3.99),
        ("2_stars", 2.0, 2.99),
        ("1_star", 1.0, 1.99),
    ]

    result = {}
    for range_name, min_rating, max_rating in rating_ranges:
        count = (
            db.query(func.count(avg_ratings.c.book_id))
            .filter(
                avg_ratings.c.avg_rating >= min_rating,
                avg_ratings.c.avg_rating <= max_rating,
            )
            .scalar()
        )
        result[range_name] = count or 0

    # Knjige bez ocjena
    books_without_ratings = (
        db.query(func.count(Book.id))
        .outerjoin(Rating, Book.id == Rating.book_id)
        .filter(Rating.id == None)
        .scalar()
    )

    result["no_ratings"] = books_without_ratings or 0

    return {
        "distribution": result,
        "total_rated_books": sum(result.values()) - result["no_ratings"],
        "total_unrated_books": result["no_ratings"],
    }


# ─── REAL-TIME STATISTIKE (WebSocket) ────────────────────────────────────────


async def broadcast_stats_update(db: Session):
    """Pošalji ažuriranje statistika svim spojenim klijentima."""
    try:
        today = date.today()
        total_books = db.query(func.count(Book.id)).scalar() or 0
        total_members = db.query(func.count(Member.id)).scalar() or 0
        active_members = (
            db.query(func.count(Member.id)).filter(Member.is_active == True).scalar()
            or 0
        )
        total_loans = db.query(func.count(Loan.id)).scalar() or 0
        active_loans = (
            db.query(func.count(Loan.id)).filter(Loan.is_returned == False).scalar()
            or 0
        )
        overdue_loans = (
            db.query(func.count(Loan.id))
            .filter(Loan.is_returned == False, Loan.due_date < today)
            .scalar()
            or 0
        )

        stats = {
            "total_books": total_books,
            "total_members": total_members,
            "active_members": active_members,
            "total_loans": total_loans,
            "active_loans": active_loans,
            "overdue_loans": overdue_loans,
            "timestamp": datetime.now().isoformat(),
        }

        await notify_stats_updated(stats)
    except Exception as e:
        print(f"Greška pri slanju statistika: {e}")


@router.post("/broadcast-update")
async def broadcast_stats(
    background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """
    Ručno pokreni broadcast ažuriranja statistika.
    Korisno za testiranje ili nakon većih promjena.
    """
    await broadcast_stats_update(db)
    return {"message": "Statistike poslane svim spojenim klijentima"}


# ─── DODATNE STATISTIKE ────────────────────────────────────────────────────────


@router.get("/member-activity-monthly")
def get_member_activity_monthly(
    year: Optional[int] = Query(None, description="Godina"),
    db: Session = Depends(get_db),
):
    """
    Pristupi članova po mjesecima (broj posudbi po članu).
    """
    if not year:
        year = datetime.now().year

    activity = (
        db.query(
            Member.id,
            Member.first_name,
            Member.last_name,
            func.count(Loan.id).label("loan_count"),
        )
        .join(Loan, Member.id == Loan.member_id)
        .filter(extract("year", Loan.loan_date) == year)
        .group_by(Member.id, Member.first_name, Member.last_name)
        .order_by(func.count(Loan.id).desc())
        .limit(50)
        .all()
    )

    return [
        {
            "member_id": m.id,
            "name": f"{m.first_name} {m.last_name}",
            "loan_count": m.loan_count,
        }
        for m in activity
    ]


@router.get("/top-members-by-loans")
def get_top_members_by_loans(
    limit: Optional[int] = Query(10, ge=1, le=100), db: Session = Depends(get_db)
):
    """
    Članovi s najviše posuđenih knjiga (ukupno).
    """
    members = (
        db.query(
            Member.id,
            Member.first_name,
            Member.last_name,
            Member.member_number,
            func.count(Loan.id).label("total_loans"),
            func.sum(case((Loan.is_returned == True, 1), else_=0)).label(
                "returned_loans"
            ),
        )
        .join(Loan, Member.id == Loan.member_id)
        .group_by(Member.id, Member.first_name, Member.last_name, Member.member_number)
        .order_by(func.count(Loan.id).desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "member_id": m.id,
            "name": f"{m.first_name} {m.last_name}",
            "member_number": m.member_number,
            "total_loans": m.total_loans,
            "returned_loans": m.returned_loans,
        }
        for m in members
    ]


@router.get("/members-with-longest-loans")
def get_members_with_longest_loans(
    limit: Optional[int] = Query(10, ge=1, le=100), db: Session = Depends(get_db)
):
    """
    Članovi s najdužim prosječnim trajanjem posudbe.
    """
    today = date.today()

    # FIXED v8.1: Use julianday for cross-DB date diff
    members = (
        db.query(
            Member.id,
            Member.first_name,
            Member.last_name,
            func.avg(
                case(
                    (
                        Loan.is_returned == True,
                        func.julianday(Loan.return_date)
                        - func.julianday(Loan.loan_date),
                    ),
                    (
                        Loan.is_returned == False,
                        func.julianday("date('now')") - func.julianday(Loan.loan_date),
                    ),
                    else_=literal(0),
                )
            ).label("avg_loan_days"),
            func.count(Loan.id).label("total_loans"),
        )
        .join(Loan, Member.id == Loan.member_id)
        .filter(
            Loan.loan_date.isnot(None),
            Loan.return_date.isnot(None) | (Loan.is_returned == False),
        )
        .group_by(Member.id, Member.first_name, Member.last_name)
        .having(func.count(Loan.id) >= 3)
        .order_by(
            func.avg(
                case(
                    (
                        Loan.is_returned == True,
                        func.julianday(Loan.return_date)
                        - func.julianday(Loan.loan_date),
                    ),
                    (
                        Loan.is_returned == False,
                        func.julianday("date('now')") - func.julianday(Loan.loan_date),
                    ),
                    else_=literal(0),
                )
            ).desc()
        )
        .limit(limit)
        .all()
    )

    return [
        {
            "member_id": m.id,
            "name": f"{m.first_name} {m.last_name}",
            "avg_loan_days": round(float(m.avg_loan_days), 1) if m.avg_loan_days else 0,
            "total_loans": m.total_loans,
        }
        for m in members
    ]


@router.get("/most-reserved")
def get_most_reserved(
    limit: Optional[int] = Query(10, ge=1, le=100), db: Session = Depends(get_db)
):
    """
    Najtraženije knjige (po broju rezervacija).
    """
    from app.models.models import Reservation

    books = (
        db.query(
            Book.id,
            Book.title,
            Book.author,
            Book.isbn,
            func.count(Reservation.id).label("reservation_count"),
        )
        .join(Reservation, Book.id == Reservation.book_id)
        .group_by(Book.id, Book.title, Book.author, Book.isbn)
        .order_by(func.count(Reservation.id).desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "book_id": b.id,
            "title": b.title,
            "author": b.author,
            "isbn": b.isbn,
            "reservation_count": b.reservation_count,
        }
        for b in books
    ]


@router.get("/average-loan-duration")
def get_average_loan_duration(db: Session = Depends(get_db)):
    """
    Prosječno vrijeme posudbe.
    """
    today = date.today()

    # Za vraćene posudbe
    # FIXED: SQLite julianday() for safe date diff
    # FIXED v8.1: Use SQL date functions instead of Python literal
    returned_avg = (
        db.query(
            func.avg(func.julianday(Loan.return_date) - func.julianday(Loan.loan_date))
        )
        .filter(
            Loan.is_returned == True,
            Loan.return_date.isnot(None),
            Loan.loan_date.isnot(None),
        )
        .scalar()
        or 0
    )

    # Za aktivne posudbe - FIXED: Use date('now')
    active_avg = (
        db.query(
            func.avg(func.julianday("date('now')") - func.julianday(Loan.loan_date))
        )
        .filter(Loan.is_returned == False, Loan.loan_date.isnot(None))
        .scalar()
        or 0
    )

    # Ukupno - FIXED
    all_avg = (
        db.query(
            func.avg(
                case(
                    (
                        Loan.is_returned == True,
                        func.julianday(Loan.return_date)
                        - func.julianday(Loan.loan_date),
                    ),
                    (
                        Loan.is_returned == False,
                        func.julianday("date('now')") - func.julianday(Loan.loan_date),
                    ),
                    else_=literal(0),
                )
            )
        )
        .filter(Loan.return_date.isnot(None) | (Loan.is_returned == False))
        .scalar()
        or 0
    )

    return {
        "returned_loans_avg_days": round(float(returned_avg), 1) if returned_avg else 0,
        "active_loans_avg_days": round(float(active_avg), 1) if active_avg else 0,
        "overall_avg_days": round(float(all_avg), 1) if all_avg else 0,
    }


@router.get("/daily-stats")
def get_daily_stats(db: Session = Depends(get_db)):
    """
    Dnevne statistike (danas, ovaj tjedan, prošli tjedan).
    """
    today = date.today()
    start_of_today = datetime.combine(today, datetime.min.time())
    start_of_week = today - timedelta(days=today.weekday())
    start_of_last_week = start_of_week - timedelta(days=7)
    end_of_last_week = start_of_week - timedelta(seconds=1)

    # Danas
    today_loans = db.query(Loan).filter(func.date(Loan.loan_date) == today).count()

    today_returns = (
        db.query(Loan)
        .filter(func.date(Loan.return_date) == today, Loan.is_returned == True)
        .count()
    )

    today_new_members = (
        db.query(Member).filter(func.date(Member.created_at) == today).count()
        if hasattr(Member, "created_at")
        else 0
    )

    today_overdue = (
        db.query(Loan).filter(Loan.is_returned == False, Loan.due_date < today).count()
    )

    # Ovaj tjedan
    this_week_loans = (
        db.query(Loan)
        .filter(Loan.loan_date >= start_of_week, Loan.loan_date <= today)
        .count()
    )

    # Prošli tjedan
    last_week_loans = (
        db.query(Loan)
        .filter(
            Loan.loan_date >= start_of_last_week, Loan.loan_date <= end_of_last_week
        )
        .count()
    )

    # Trend
    if last_week_loans > 0:
        trend = round(((this_week_loans - last_week_loans) / last_week_loans) * 100, 1)
    else:
        trend = 100 if this_week_loans > 0 else 0

    return {
        "today": {
            "loans": today_loans,
            "returns": today_returns,
            "new_members": today_new_members,
            "overdue": today_overdue,
        },
        "this_week": {"loans": this_week_loans},
        "last_week": {"loans": last_week_loans},
        "trend": {
            "percentage": trend,
            "direction": "up" if trend > 0 else "down" if trend < 0 else "stable",
        },
        "date": today.isoformat(),
    }


@router.get("/recommendations-for-acquisition")
def get_acquisition_recommendations(
    limit: Optional[int] = Query(10, ge=1, le=50), db: Session = Depends(get_db)
):
    """
    Preporučene knjige za nabavu na temelju potražnje.
    Analizira žanrove i autore s najviše posudbi i najmanje dostupnih primjeraka.
    """
    # Žanrovi s najviše posudbi
    genre_demand = (
        db.query(
            Book.genre,
            func.count(Loan.id).label("loan_count"),
            func.sum(Book.available_copies).label("available_copies"),
            func.count(Book.id).label("book_count"),
        )
        .join(Loan, Book.id == Loan.book_id)
        .filter(Book.genre != None)
        .group_by(Book.genre)
        .order_by(func.count(Loan.id).desc())
        .limit(10)
        .all()
    )

    # Autori s najviše posudbi
    author_demand = (
        db.query(
            Book.author,
            func.count(Loan.id).label("loan_count"),
            func.sum(Book.available_copies).label("available_copies"),
            func.count(Book.id).label("book_count"),
        )
        .join(Loan, Book.id == Loan.book_id)
        .group_by(Book.author)
        .order_by(func.count(Loan.id).desc())
        .limit(10)
        .all()
    )

    return {
        "by_genre": [
            {
                "genre": g.genre or "Nedefinirano",
                "loan_count": g.loan_count,
                "available_copies": g.available_copies or 0,
                "book_count": g.book_count,
                "recommendation": (
                    "Nabavi"
                    if (g.available_copies or 0) < g.loan_count * 0.5
                    else "Prati"
                ),
            }
            for g in genre_demand
        ],
        "by_author": [
            {
                "author": a.author or "Nedefinirano",
                "loan_count": a.loan_count,
                "available_copies": a.available_copies or 0,
                "book_count": a.book_count,
                "recommendation": (
                    "Nabavi"
                    if (a.available_copies or 0) < a.loan_count * 0.5
                    else "Prati"
                ),
            }
            for a in author_demand
        ],
    }


@router.get("/satisfaction-rate")
def get_satisfaction_rate(db: Session = Depends(get_db)):
    """
    Stopa zadovoljstva članova (na temelju ocjena).
    """
    # Prosječna ocjena
    avg_rating = db.query(func.avg(Rating.rating)).scalar() or 0

    # Ukupan broj ocjena
    total_ratings = db.query(func.count(Rating.id)).scalar() or 0

    # Raspodjela ocjena
    rating_distribution = (
        db.query(Rating.rating, func.count(Rating.id).label("count"))
        .group_by(Rating.rating)
        .order_by(Rating.rating.desc())
        .all()
    )

    # Aktivni članovi s posudbama
    active_members_with_loans = (
        db.query(func.count(func.distinct(Member.id)))
        .join(Loan, Member.id == Loan.member_id)
        .filter(Member.is_active == True)
        .scalar()
    ) or 0

    # Članovi koji su ocijenili knjige
    members_who_rated = (
        db.query(func.count(func.distinct(Rating.member_id))).scalar()
    ) or 0

    satisfaction_rate = (
        round((members_who_rated / active_members_with_loans * 100), 1)
        if active_members_with_loans > 0
        else 0
    )

    return {
        "average_rating": round(float(avg_rating), 2),
        "total_ratings": total_ratings,
        "distribution": {f"{r.rating}_stars": r.count for r in rating_distribution},
        "active_members_with_loans": active_members_with_loans,
        "members_who_rated": members_who_rated,
        "satisfaction_rate": satisfaction_rate,
    }
