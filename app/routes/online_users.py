"""
Online users router for real-time presence tracking.

ISPRAVCI v8.3:
  - Import online_users iz websocket_router (ispravan, registriran router)
  - Dodan nedostajući import datetime
  - Popravljeno: timestamp se šalje kao datetime objekt (ne string)
"""

from datetime import datetime, timezone
from typing import Dict

from app.auth import get_current_user
from app.database import get_db
from app.routes.websocket_router import online_users
from app.schemas.online_user import OnlineUserOut, OnlineUsersResponse
from app.websocket import broadcast_active_users
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

router = APIRouter(prefix="/online-users", tags=["Online Korisnici"])


@router.get("/", response_model=OnlineUsersResponse)
async def get_online_users(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Dohvati listu trenutno online korisnika.
    Čita iz WebSocket presence trackinga (in-memory rječnik).
    """
    users_list = []
    now = datetime.now(timezone.utc)

    for client_id, user_data in online_users.items():
        try:
            users_list.append(
                OnlineUserOut(
                    user_id=int(user_data["user_id"]),
                    username=user_data["username"],
                    full_name=None,
                    role=user_data["role"],
                    client_type=user_data["client_type"],
                    connected_at=datetime.fromisoformat(user_data["connected_at"]),
                    last_seen=(
                        datetime.fromisoformat(user_data["last_seen"])
                        if "last_seen" in user_data
                        else None
                    ),
                )
            )
        except (ValueError, KeyError, TypeError) as exc:
            print(f"Greška pri parsiranju online korisnika {client_id}: {exc}")

    await broadcast_active_users()

    return OnlineUsersResponse(
        online_users=users_list,
        total=len(users_list),
        timestamp=now,
    )


@router.get("/count")
async def get_online_count(current_user=Depends(get_current_user)):
    """Brzi endpoint za broj online korisnika."""
    return {
        "online_count": len(online_users),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
