"""
app/routes/reservations.py
VERZIJA: 9.1.4 — Paginacija (PagedResponse) na list endpointu
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.auth import get_current_user, get_library_id, require_staff
from app.database import get_db
from app.models.models import Book, Member, Reservation
from app.models.user import User
from app.schemas.schemas import ReservationCreate, ReservationOut, PagedResponse

router = APIRouter(prefix="/reservations", tags=["Rezervacije"])


def _res_query(db: Session, library_id: Optional[int]):
    q = db.query(Reservation)
    if library_id is not None:
        q = q.filter(Reservation.library_id == library_id)
    return q


@router.get("/", response_model=PagedResponse[ReservationOut])
def get_reservations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    member_id: int = None,
    book_id: int = None,
    active_only: bool = True,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db)
):
    query = _res_query(db, library_id)
    if member_id:   query = query.filter(Reservation.member_id == member_id)
    if book_id:     query = query.filter(Reservation.book_id == book_id)
    if active_only: query = query.filter(Reservation.is_active == True)
    total = query.count()
    items = query.offset(skip).limit(limit).all()
    return PagedResponse.create(items=items, total=total, skip=skip, limit=limit)


@router.post("/", response_model=ReservationOut, status_code=201)
def create_reservation(
    res: ReservationCreate,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db)
):
    if not current_user.library_id:
        raise HTTPException(status_code=400, detail="Korisnik nije dodijeljen knjižnici")

    lib_id = current_user.library_id
    book = db.query(Book).filter(Book.id == res.book_id, Book.library_id == lib_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")

    member = db.query(Member).filter(Member.id == res.member_id, Member.library_id == lib_id).first()
    if not member or not member.is_active:
        raise HTTPException(status_code=404, detail="Član nije pronađen ili nije aktivan")

    existing = _res_query(db, lib_id).filter(
        Reservation.book_id == res.book_id,
        Reservation.member_id == res.member_id,
        Reservation.is_active == True
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Rezervacija već postoji")

    db_res = Reservation(**res.model_dump(), library_id=lib_id)
    db.add(db_res)
    db.commit()
    db.refresh(db_res)
    return db_res


@router.put("/{res_id}/cancel", response_model=ReservationOut)
def cancel_reservation(
    res_id: int,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db)
):
    reservation = _res_query(db, current_user.library_id).filter(Reservation.id == res_id).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Rezervacija nije pronađena")
    reservation.is_active = False
    db.commit()
    db.refresh(reservation)
    return reservation




# BUG-4 FIX: Flutter šalje PATCH /{id}/cancel — dodaj alias
@router.patch("/{res_id}/cancel")
def cancel_reservation_patch_alias(
    res_id: int,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db)
):
    return cancel_reservation(res_id, current_user, db)
@router.delete("/{res_id}", status_code=204)
def delete_reservation(
    res_id: int,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db)
):
    reservation = _res_query(db, current_user.library_id).filter(Reservation.id == res_id).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Rezervacija nije pronađena")
    db.delete(reservation)
    db.commit()
