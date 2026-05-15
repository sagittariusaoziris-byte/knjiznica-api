"""
app/routes/stats.py — VERZIJA 9.0.0 — library_id filter na svim upitima
"""
from datetime import date, datetime, timedelta
from typing import Optional

from app.auth import get_library_id
from app.database import get_db
from app.models.models import Book, Loan, Member, Rating, Reservation
from app.websocket import notify_stats_updated
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import case, extract, func, literal
from sqlalchemy.orm import Session

router = APIRouter(prefix="/stats", tags=["Statistike"])


def _filter(q, model, library_id):
    if library_id is not None:
        q = q.filter(model.library_id == library_id)
    return q


@router.get("/")
def get_stats_root(
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    return get_library_summary(library_id=library_id, db=db)


@router.get("/summary")
def get_library_summary(
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    today = date.today()
    bq = _filter(db.query(Book), Book, library_id)
    mq = _filter(db.query(Member), Member, library_id)
    lq = _filter(db.query(Loan), Loan, library_id)
    rq = _filter(db.query(Rating), Rating, library_id)

    total_books   = bq.count()
    total_members = mq.count()
    active_members = mq.filter(Member.is_active == True).count()
    total_loans   = lq.count()
    active_loans  = lq.filter(Loan.is_returned == False).count()
    overdue_loans = lq.filter(Loan.is_returned == False, Loan.due_date < today).count()
    current_month_loans = lq.filter(
        extract("year",  Loan.loan_date) == today.year,
        extract("month", Loan.loan_date) == today.month,
    ).count()
    avg_rating = db.query(func.avg(Rating.rating)).scalar()
    if library_id:
        avg_rating = rq.with_entities(func.avg(Rating.rating)).scalar()
    avg_rating = round(float(avg_rating), 2) if avg_rating else 0

    genre_stats = bq.with_entities(Book.genre, func.count(Book.id)).filter(
        Book.genre.isnot(None)
    ).group_by(Book.genre).order_by(func.count(Book.id).desc()).first()

    return {
        "books": {
            "total": total_books,
            "available_copies": bq.with_entities(func.sum(Book.available_copies)).scalar() or 0,
            "total_copies": bq.with_entities(func.sum(Book.total_copies)).scalar() or 0,
        },
        "members": {"total": total_members, "active": active_members, "inactive": total_members - active_members},
        "loans": {"total": total_loans, "active": active_loans, "overdue": overdue_loans, "this_month": current_month_loans},
        "ratings": {"average": avg_rating},
        "popular_genre": {"name": genre_stats[0] if genre_stats else None, "count": genre_stats[1] if genre_stats else 0},
        "analysis_date": today.isoformat(),
        "library_id": library_id,
    }


@router.get("/popular-books")
def get_popular_books(
    limit: Optional[int] = Query(10, ge=1, le=100),
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    lq = db.query(Loan.book_id, func.count(Loan.id).label("loan_count"))
    if library_id:
        lq = lq.filter(Loan.library_id == library_id)
    loan_count_subq = lq.group_by(Loan.book_id).subquery()

    bq = db.query(Book, loan_count_subq.c.loan_count).join(
        loan_count_subq, Book.id == loan_count_subq.c.book_id
    )
    if library_id:
        bq = bq.filter(Book.library_id == library_id)
    books = bq.order_by(loan_count_subq.c.loan_count.desc()).limit(limit).all()

    return [{"id": b.id, "title": b.title, "author": b.author, "isbn": b.isbn,
             "genre": b.genre, "shelf": b.shelf, "loan_count": count} for b, count in books]


@router.get("/active-members")
def get_active_members(
    limit: Optional[int] = Query(10, ge=1, le=100),
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    lq = db.query(Loan.member_id, func.count(Loan.id).label("loan_count"))
    if library_id:
        lq = lq.filter(Loan.library_id == library_id)
    subq = lq.group_by(Loan.member_id).subquery()

    mq = db.query(Member, subq.c.loan_count).join(subq, Member.id == subq.c.member_id)
    if library_id:
        mq = mq.filter(Member.library_id == library_id)
    members = mq.order_by(subq.c.loan_count.desc()).limit(limit).all()

    return [{"id": m.id, "member_number": m.member_number, "first_name": m.first_name,
             "last_name": m.last_name, "email": m.email, "loan_count": count} for m, count in members]


@router.get("/loans-by-month")
def get_loans_by_month(
    year: Optional[int] = Query(None),
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    if not year:
        year = datetime.now().year
    lq = db.query(extract("month", Loan.loan_date).label("month"), func.count(Loan.id).label("count"))
    if library_id:
        lq = lq.filter(Loan.library_id == library_id)
    loans_by_month = lq.filter(extract("year", Loan.loan_date) == year).group_by(
        extract("month", Loan.loan_date)).order_by(extract("month", Loan.loan_date)).all()

    result = []
    for m in range(1, 13):
        count = next((c for mo, c in loans_by_month if int(mo) == m), 0)
        result.append({"month": m, "month_name": date(2000, m, 1).strftime("%B"), "count": count})
    return {"year": year, "monthly_loans": result, "total_loans": sum(i["count"] for i in result)}


@router.get("/overdue-analysis")
def get_overdue_analysis(
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    today = date.today()
    lq = _filter(db.query(Loan), Loan, library_id).filter(Loan.is_returned == False, Loan.due_date < today)
    total_overdue = lq.count()
    overdue_loans = lq.all()
    days_dict = {}
    for loan in overdue_loans:
        days = (today - loan.due_date).days
        days_dict[days] = days_dict.get(days, 0) + 1
    categories = {
        "1-7_dana":   sum(1 for l in overdue_loans if 1  <= (today - l.due_date).days <= 7),
        "8-30_dana":  sum(1 for l in overdue_loans if 8  <= (today - l.due_date).days <= 30),
        "31-90_dana": sum(1 for l in overdue_loans if 31 <= (today - l.due_date).days <= 90),
        "90+_dana":   sum(1 for l in overdue_loans if (today - l.due_date).days > 90),
    }
    return {"total_overdue": total_overdue, "categories": categories,
            "overdue_by_days": sorted([{"days_overdue": d, "count": c} for d, c in days_dict.items()],
                                      key=lambda x: x["days_overdue"], reverse=True)[:30],
            "analysis_date": today.isoformat()}


@router.get("/shelf-occupancy")
def get_shelf_occupancy(
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    q = db.query(Book.shelf, func.count(Book.id).label("book_count"),
                 func.sum(Book.total_copies).label("total_copies"),
                 func.sum(Book.available_copies).label("available_copies"))
    if library_id:
        q = q.filter(Book.library_id == library_id)
    shelf_stats = q.group_by(Book.shelf).order_by(func.count(Book.id).desc()).all()

    result = []
    for shelf, count, total, available in shelf_stats:
        total = total or 0; available = available or 0
        occupied = total - available
        result.append({"shelf": shelf or "Nedefinirano", "book_count": count,
                       "total_copies": total, "available_copies": available,
                       "occupied_copies": occupied,
                       "occupancy_rate": round((occupied / total * 100), 2) if total > 0 else 0})
    return {"shelves": result,
            "summary": {"total_shelves": len(result),
                        "total_books": sum(i["book_count"] for i in result),
                        "total_copies": sum(i["total_copies"] for i in result),
                        "total_available": sum(i["available_copies"] for i in result),
                        "overall_occupancy_rate": round(
                            (sum(i["occupied_copies"] for i in result) /
                             sum(i["total_copies"] for i in result) * 100), 2)
                        if sum(i["total_copies"] for i in result) > 0 else 0}}


@router.get("/daily-stats")
def get_daily_stats(
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    start_of_last_week = start_of_week - timedelta(days=7)
    end_of_last_week = start_of_week - timedelta(days=1)

    def lf(q): return q.filter(Loan.library_id == library_id) if library_id else q
    def mf(q): return q.filter(Member.library_id == library_id) if library_id else q

    today_loans   = lf(db.query(Loan)).filter(func.date(Loan.loan_date) == today).count()
    today_returns = lf(db.query(Loan)).filter(func.date(Loan.return_date) == today, Loan.is_returned == True).count()
    today_members = mf(db.query(Member)).filter(func.date(Member.created_at) == today).count()
    today_overdue = lf(db.query(Loan)).filter(Loan.is_returned == False, Loan.due_date < today).count()
    this_week = lf(db.query(Loan)).filter(Loan.loan_date >= start_of_week, Loan.loan_date <= today).count()
    last_week = lf(db.query(Loan)).filter(Loan.loan_date >= start_of_last_week, Loan.loan_date <= end_of_last_week).count()
    trend = round(((this_week - last_week) / last_week * 100), 1) if last_week > 0 else (100 if this_week > 0 else 0)

    return {"today": {"loans": today_loans, "returns": today_returns, "new_members": today_members, "overdue": today_overdue},
            "this_week": {"loans": this_week}, "last_week": {"loans": last_week},
            "trend": {"percentage": trend, "direction": "up" if trend > 0 else "down" if trend < 0 else "stable"},
            "date": today.isoformat()}


@router.get("/most-reserved")
def get_most_reserved(
    limit: Optional[int] = Query(10, ge=1, le=100),
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    q = db.query(Book.id, Book.title, Book.author, Book.isbn, func.count(Reservation.id).label("count"))
    q = q.join(Reservation, Book.id == Reservation.book_id)
    if library_id:
        q = q.filter(Reservation.library_id == library_id)
    books = q.group_by(Book.id, Book.title, Book.author, Book.isbn).order_by(func.count(Reservation.id).desc()).limit(limit).all()
    return [{"book_id": b.id, "title": b.title, "author": b.author, "isbn": b.isbn, "reservation_count": b.count} for b in books]


@router.post("/broadcast-update")
async def broadcast_stats(
    background_tasks: BackgroundTasks,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    stats = get_library_summary(library_id=library_id, db=db)
    await notify_stats_updated(stats)
    return {"message": "Statistike poslane"}
