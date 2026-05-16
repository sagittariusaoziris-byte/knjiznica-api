"""
app/routes/notifications.py — VERZIJA 9.0.0 — library_id filter
"""
import json
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_library_id, require_any
from app.database import get_db
from app.models.notification import Notification
from app.models.user import User

router = APIRouter(prefix="/notifications", tags=["Obavijesti"])


def _utcnow():
    return datetime.now(timezone.utc)


class NotificationOut(BaseModel):
    id: int
    user_id: Optional[int] = None
    library_id: Optional[int] = None
    type: str
    priority: str
    title: str
    message: str
    is_read: bool
    data: Optional[dict] = None
    created_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_with_data(cls, obj):
        data = {}
        if obj.data:
            if isinstance(obj.data, dict):
                data = obj.data
            else:
                try:
                    data = json.loads(obj.data)
                except Exception:
                    data = {}
        return cls(
            id=obj.id, user_id=obj.user_id, library_id=getattr(obj, "library_id", None),
            type=obj.type, priority=obj.priority, title=obj.title, message=obj.message,
            is_read=obj.is_read, data=data,
            created_at=obj.created_at if obj.created_at else _utcnow(),
        )


class NotificationCreate(BaseModel):
    user_id: Optional[int] = None
    type: str = "system"
    priority: str = "medium"
    title: str
    message: str
    data: Optional[dict] = None


def _notif_query(db, library_id, user_id=None):
    q = db.query(Notification)
    if library_id is not None:
        q = q.filter(Notification.library_id == library_id)
    if user_id:
        q = q.filter((Notification.user_id == user_id) | (Notification.user_id == None))
    return q


@router.get("/", response_model=List[NotificationOut])
def get_notifications(
    limit: int = 50,
    unread_only: bool = False,
    library_id: Optional[int] = Depends(get_library_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    q = _notif_query(db, library_id, current_user.id)
    if unread_only:
        q = q.filter(Notification.is_read == False)
    notifs = q.order_by(Notification.created_at.desc()).limit(limit).all()
    return [NotificationOut.from_orm_with_data(n) for n in notifs]


@router.get("/stats")
def get_notification_stats(
    days: Optional[int] = None,
    library_id: Optional[int] = Depends(get_library_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from datetime import timedelta
    q = _notif_query(db, library_id, current_user.id)
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        q = q.filter(Notification.created_at >= cutoff)
    total   = q.count()
    unread  = q.filter(Notification.is_read == False).count()
    return {"total": total, "unread": unread, "read": total - unread}


@router.post("/mark-read/{notif_id}")
def mark_read(
    notif_id: int,
    library_id: Optional[int] = Depends(get_library_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    notif = _notif_query(db, library_id).filter(Notification.id == notif_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Obavijest nije pronađena")
    notif.is_read = True
    db.commit()
    return {"success": True}


@router.put("/{notif_id}/read")
def mark_read_put(
    notif_id: int,
    library_id: Optional[int] = Depends(get_library_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Alias za Flutter klijent koji šalje PUT /{id}/read."""
    notif = _notif_query(db, library_id).filter(Notification.id == notif_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Obavijest nije pronađena")
    notif.is_read = True
    db.commit()
    return {"success": True}


@router.post("/mark-all-read")
def mark_all_read(
    library_id: Optional[int] = Depends(get_library_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    _notif_query(db, library_id, current_user.id).filter(
        Notification.is_read == False
    ).update({"is_read": True})
    db.commit()
    return {"success": True}


@router.post("/", response_model=NotificationOut)
def create_notification(
    data: NotificationCreate,
    library_id: Optional[int] = Depends(get_library_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    notif = Notification(
        library_id=library_id,
        user_id=data.user_id,
        type=data.type,
        priority=data.priority,
        title=data.title,
        message=data.message,
        data=data.data or {},
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return NotificationOut.from_orm_with_data(notif)


@router.delete("/{notif_id}", status_code=204)
def delete_notification(
    notif_id: int,
    library_id: Optional[int] = Depends(get_library_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    notif = _notif_query(db, library_id, current_user.id).filter(Notification.id == notif_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Obavijest nije pronađena")
    db.delete(notif)
    db.commit()


@router.get("/poll")
def poll_notifications(
    since_id: int = 0,
    library_id: Optional[int] = Depends(get_library_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    q = _notif_query(db, library_id, current_user.id).filter(
        Notification.id > since_id, Notification.is_read == False
    )
    notifs = q.order_by(Notification.created_at.desc()).limit(20).all()
    return {"notifications": [NotificationOut.from_orm_with_data(n) for n in notifs],
            "count": len(notifs)}
