"""
app/routes/notifications.py
Ruta za obavijesti (Notifications)

POPRAVAK v8.3.1 (14.04.2026):
  500 greška na GET /notifications/?limit=100
  Uzrok: neke obavijesti u bazi imaju created_at = NULL
          (tablica kreirana bez NOT NULL constrainta u migrate_v8_3.sql)
  Fix #1: from_orm_with_data — fallback: obj.created_at or datetime.utcnow()
  Fix #2: migrate_fix_v8_3_1.sql — UPDATE NULL redova + ALTER COLUMN NOT NULL

PRETHODNI PROBLEM (v8.3.0):
  Flutter poziva /notifications/*, /notifications/poll, /notifications/stats
  ali ta ruta NIJE bila registrirana u main.py → 500 Server Error.
  Riješeno dodavanjem u app/main.py:
    from app.routes import notifications as notifications_router
    app.include_router(notifications_router.router)
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_any
from app.database import get_db
from app.models.notification import Notification
from app.models.user import User

router = APIRouter(prefix="/notifications", tags=["Obavijesti"])


# ── Helper ─────────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    """Vraća trenutni UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


# ── Schemas ────────────────────────────────────────────────────────────────────

class NotificationOut(BaseModel):
    id: int
    user_id: Optional[int] = None
    type: str
    priority: str
    title: str
    message: str
    is_read: bool
    data: Optional[dict] = None
    created_at: datetime  # nikad None nakon popravka

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_with_data(cls, obj):
        """
        Konstruktor iz SQLAlchemy objekta.
        FIX: created_at fallback na utcnow() ako je NULL u bazi.
        """
        # Parsiranje data polja
        data = {}
        if obj.data:
            if isinstance(obj.data, dict):
                data = obj.data
            else:
                try:
                    data = json.loads(obj.data)
                except Exception:
                    data = {}

        # FIX: zaštita od NULL created_at
        # Uzrok: tablica kreirana bez NOT NULL, stari redovi nemaju timestamp.
        # Trajno rješenje: pokrenuti migrate_fix_v8_3_1.sql na Supabase.
        created_at = obj.created_at
        if created_at is None:
            created_at = _utcnow()

        return cls(
            id=obj.id,
            user_id=obj.user_id,
            type=obj.type,
            priority=obj.priority,
            title=obj.title,
            message=obj.message,
            is_read=obj.is_read,
            data=data,
            created_at=created_at,
        )


class NotificationCreate(BaseModel):
    user_id: Optional[int] = None
    type: str = "system"
    priority: str = "medium"
    title: str
    message: str
    data: Optional[dict] = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[NotificationOut])
async def get_notifications(
    unread_only: bool = False,
    type_filter: Optional[str] = None,
    days: Optional[int] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dohvati obavijesti za trenutnog korisnika."""
    query = db.query(Notification).filter(
        (Notification.user_id == current_user.id) | (Notification.user_id.is_(None))
    )
    if unread_only:
        query = query.filter(Notification.is_read == False)
    if type_filter:
        query = query.filter(Notification.type == type_filter)
    if days:
        cutoff = _utcnow() - timedelta(days=days)
        query = query.filter(Notification.created_at >= cutoff)

    notifications = query.order_by(Notification.created_at.desc()).limit(limit).all()
    return [NotificationOut.from_orm_with_data(n) for n in notifications]


@router.get("/stats")
async def get_notification_stats(
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Statistike obavijesti za trenutnog korisnika."""
    cutoff = _utcnow() - timedelta(days=days)
    total = db.query(Notification).filter(
        (Notification.user_id == current_user.id) | (Notification.user_id.is_(None)),
        Notification.created_at >= cutoff,
    ).count()
    unread = db.query(Notification).filter(
        (Notification.user_id == current_user.id) | (Notification.user_id.is_(None)),
        Notification.is_read == False,
        Notification.created_at >= cutoff,
    ).count()
    return {"total": total, "unread": unread, "days": days}


@router.get("/poll")
async def poll_notifications(
    since: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HTTP polling fallback — dohvati nove obavijesti od zadnjeg ID-a."""
    notifications = db.query(Notification).filter(
        (Notification.user_id == current_user.id) | (Notification.user_id.is_(None)),
        Notification.id > since,
    ).order_by(Notification.id.asc()).limit(50).all()

    results = []
    for n in notifications:
        data = {}
        if n.data:
            if isinstance(n.data, dict):
                data = n.data
            else:
                try:
                    data = json.loads(n.data)
                except Exception:
                    pass
        results.append({
            "id": n.id,
            "type": n.type,
            "priority": n.priority,
            "title": n.title,
            "message": n.message,
            "is_read": n.is_read,
            "data": data,
            # FIX: zaštita od NULL
            "created_at": n.created_at.isoformat() if n.created_at else _utcnow().isoformat(),
            "user_id": n.user_id,
        })

    last_id = notifications[-1].id if notifications else since
    return {"notifications": results, "last_id": last_id}


@router.put("/{notification_id}/read")
async def mark_as_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Označi obavijest kao pročitanu."""
    n = db.query(Notification).filter(Notification.id == notification_id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Obavijest nije pronađena")
    n.is_read = True
    db.commit()
    return {"detail": "Označeno kao pročitano"}


@router.post("/mark-all-read")
async def mark_all_read(
    type_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Označi sve obavijesti kao pročitane."""
    query = db.query(Notification).filter(
        (Notification.user_id == current_user.id) | (Notification.user_id.is_(None)),
        Notification.is_read == False,
    )
    if type_filter:
        query = query.filter(Notification.type == type_filter)
    query.update({"is_read": True}, synchronize_session=False)
    db.commit()
    return {"detail": "Sve označeno kao pročitano"}


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Obriši obavijest."""
    n = db.query(Notification).filter(Notification.id == notification_id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Obavijest nije pronađena")
    db.delete(n)
    db.commit()
    return {"detail": "Obavijest obrisana"}


@router.post("/", response_model=NotificationOut, status_code=201)
async def create_notification(
    data: NotificationCreate,
    db: Session = Depends(get_db),
    _=Depends(require_any),
):
    """Kreiraj novu obavijest (interno / admin)."""
    n = Notification(
        user_id=data.user_id,
        type=data.type,
        priority=data.priority,
        title=data.title,
        message=data.message,
        data=data.data if data.data else {},
        created_at=_utcnow(),  # FIX: eksplicitno postavi timestamp
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return NotificationOut.from_orm_with_data(n)
