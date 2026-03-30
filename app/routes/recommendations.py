from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from app.database import get_db
from app.auth import get_current_user, require_staff
from app.models.recommendations import BookRecommendation, MemberBookmark, ReservationRequest
from app.models.models import Book, Member
from app.models.user import User

router = APIRouter(prefix="/recommendations", tags=["Preporuke i zahtjevi"])


# ── SCHEMAS ───────────────────────────────────────────────────────────────────

class RecommendationCreate(BaseModel):
    book_id: int
    note: Optional[str] = None

class RecommendationOut(BaseModel):
    id: int
    book_id: int
    added_by: str
    note: Optional[str]
    is_active: bool
    created_at: datetime
    book: dict

    class Config:
        from_attributes = True

class BookmarkCreate(BaseModel):
    book_id: int
    member_id: int

class RequestCreate(BaseModel):
    book_id: int
    member_id: int
    note: Optional[str] = None

class RequestUpdate(BaseModel):
    status: str  # approved, rejected
    response_note: Optional[str] = None


# ── PREPORUKE ─────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[dict])
async def get_recommendations(db: Session = Depends(get_db), _=Depends(get_current_user)):
    recs = db.query(BookRecommendation).filter(BookRecommendation.is_active == True).all()
    result = []
    for r in recs:
        book = db.query(Book).filter(Book.id == r.book_id).first()
        result.append({
            "id": r.id,
            "book_id": r.book_id,
            "added_by": r.added_by,
            "note": r.note,
            "is_active": r.is_active,
            "created_at": r.created_at.isoformat(),
            "book": {
                "id": book.id, "title": book.title, "author": book.author,
                "genre": book.genre, "year": book.year,
                "available_copies": book.available_copies
            } if book else {}
        })
    return result


@router.post("/", status_code=201)
async def create_recommendation(
    data: RecommendationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff)
):
    book = db.query(Book).filter(Book.id == data.book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")
    existing = db.query(BookRecommendation).filter(
        BookRecommendation.book_id == data.book_id,
        BookRecommendation.is_active == True
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ova knjiga je već preporučena")
    rec = BookRecommendation(
        book_id=data.book_id,
        added_by=current_user.username,
        note=data.note
    )
    db.add(rec)
    db.commit()
    return {"success": True, "id": rec.id}


@router.delete("/{rec_id}", status_code=204)
async def delete_recommendation(
    rec_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_staff)
):
    rec = db.query(BookRecommendation).filter(BookRecommendation.id == rec_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Preporuka nije pronađena")
    rec.is_active = False
    db.commit()


# ── BOOKMARKS (zvjezdice) ─────────────────────────────────────────────────────

@router.get("/bookmarks/{member_id}")
async def get_bookmarks(member_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    bookmarks = db.query(MemberBookmark).filter(MemberBookmark.member_id == member_id).all()
    return [{"id": b.id, "book_id": b.book_id, "created_at": b.created_at.isoformat()} for b in bookmarks]


@router.post("/bookmarks", status_code=201)
async def add_bookmark(data: BookmarkCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    existing = db.query(MemberBookmark).filter(
        MemberBookmark.book_id == data.book_id,
        MemberBookmark.member_id == data.member_id
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"action": "removed"}
    bookmark = MemberBookmark(book_id=data.book_id, member_id=data.member_id)
    db.add(bookmark)
    db.commit()
    return {"action": "added", "id": bookmark.id}


# ── ZAHTJEVI ZA REZERVACIJU ───────────────────────────────────────────────────

@router.get("/requests")
async def get_requests(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user)
):
    query = db.query(ReservationRequest)
    if status:
        query = query.filter(ReservationRequest.status == status)
    requests = query.order_by(ReservationRequest.created_at.desc()).all()
    result = []
    for r in requests:
        book = db.query(Book).filter(Book.id == r.book_id).first()
        member = db.query(Member).filter(Member.id == r.member_id).first()
        result.append({
            "id": r.id,
            "book_id": r.book_id,
            "member_id": r.member_id,
            "note": r.note,
            "status": r.status,
            "response_note": r.response_note,
            "created_at": r.created_at.isoformat(),
            "book": {"title": book.title, "author": book.author} if book else {},
            "member": {
                "first_name": member.first_name,
                "last_name": member.last_name,
                "member_number": member.member_number
            } if member else {}
        })
    return result


@router.post("/requests", status_code=201)
async def create_request(data: RequestCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    book = db.query(Book).filter(Book.id == data.book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")
    member = db.query(Member).filter(Member.id == data.member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Član nije pronađen")
    # Provjeri duplikat
    existing = db.query(ReservationRequest).filter(
        ReservationRequest.book_id == data.book_id,
        ReservationRequest.member_id == data.member_id,
        ReservationRequest.status == "pending"
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Zahtjev za ovu knjigu već postoji")
    req = ReservationRequest(
        book_id=data.book_id,
        member_id=data.member_id,
        note=data.note
    )
    db.add(req)
    db.commit()
    return {"success": True, "id": req.id}


@router.patch("/requests/{req_id}")
async def update_request(
    req_id: int,
    data: RequestUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_staff)
):
    req = db.query(ReservationRequest).filter(ReservationRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Zahtjev nije pronađen")
    req.status = data.status
    req.response_note = data.response_note
    db.commit()
    return {"success": True}
