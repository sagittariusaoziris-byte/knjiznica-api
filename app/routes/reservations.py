from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models.models import Reservation, Book, Member
from app.schemas.schemas import ReservationCreate, ReservationOut

router = APIRouter(prefix="/reservations", tags=["Rezervacije"])


@router.get("/", response_model=List[ReservationOut])
def get_reservations(
    member_id: int = None,
    book_id: int = None,
    active_only: bool = True,
    db: Session = Depends(get_db)
):
    query = db.query(Reservation)
    if member_id:
        query = query.filter(Reservation.member_id == member_id)
    if book_id:
        query = query.filter(Reservation.book_id == book_id)
    if active_only:
        query = query.filter(Reservation.is_active == True)
    return query.all()


@router.post("/", response_model=ReservationOut, status_code=201)
def create_reservation(res: ReservationCreate, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == res.book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")

    member = db.query(Member).filter(Member.id == res.member_id).first()
    if not member or not member.is_active:
        raise HTTPException(status_code=404, detail="Član nije pronađen ili nije aktivan")

    existing = db.query(Reservation).filter(
        Reservation.book_id == res.book_id,
        Reservation.member_id == res.member_id,
        Reservation.is_active == True
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Rezervacija već postoji")

    db_res = Reservation(**res.model_dump())
    db.add(db_res)
    db.commit()
    db.refresh(db_res)
    return db_res


@router.patch("/{reservation_id}/cancel", response_model=ReservationOut)
def cancel_reservation(reservation_id: int, db: Session = Depends(get_db)):
    res = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Rezervacija nije pronađena")
    res.is_active = False
    db.commit()
    db.refresh(res)
    return res
