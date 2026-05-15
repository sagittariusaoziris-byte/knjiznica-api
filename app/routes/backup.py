"""
app/routes/backup.py — v9.1.0
Server-side backup i restore s multitenant filtriranjem.

Endpointi:
  POST /backup/export          → JSON export podataka knjižnice
  POST /backup/export-zip      → ZIP export
  POST /backup/restore         → Restore iz JSON body-a
  GET  /backup/list            → Lista dostupnih backupa na serveru (ako je aktivan)

Sigurnost:
  - require_staff (admin ili knjiznicar)
  - Svaki endpoint automatski filtrira po library_id iz JWT tokena
  - Globalni admin (library_id=None) može vidjeti/restorirati sve
"""

import io
import json
import zipfile
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_library_id, require_staff
from app.database import get_db
from app.models.models import Book, Loan, Member
from app.models.user import User

router = APIRouter(prefix="/backup", tags=["backup"])


# ── Pomoćne funkcije ──────────────────────────────────────────────────────────

def _filter_by_lib(query, model, library_id):
    """Dodaj library_id filter samo ako nije globalni admin."""
    if library_id is not None:
        return query.filter(model.library_id == library_id)
    return query


def _build_backup(db: Session, library_id: Optional[int],
                  current_user,
                  include_books=True, include_members=True,
                  include_loans=True) -> dict:
    """Generiraj backup dict filtriran po knjižnici."""
    now = datetime.now()

    # Dohvati naziv knjižnice
    lib_name = None
    if library_id is not None:
        from app.models.library import Library
        lib = db.query(Library).filter(Library.id == library_id).first()
        lib_name = lib.name if lib else f"Library {library_id}"
    else:
        lib_name = "Globalni backup (sve knjižnice)"

    data: dict[str, Any] = {
        "version":      "9.1.0",
        "created_at":   now.isoformat(),
        "library_id":   library_id,
        "library_name": lib_name,
        "created_by":   current_user.username,
        "description":  (
            f"Backup — {lib_name} — "
            f"{now.strftime('%d.%m.%Y %H:%M')}"
        ),
    }

    if include_books:
        books = _filter_by_lib(db.query(Book), Book, library_id).all()
        data["books"] = [
            {c.name: getattr(b, c.name) for c in Book.__table__.columns}
            for b in books
        ]

    if include_members:
        members = _filter_by_lib(db.query(Member), Member, library_id).all()
        data["members"] = [
            {c.name: getattr(m, c.name) for c in Member.__table__.columns}
            for m in members
        ]

    if include_loans:
        loans = _filter_by_lib(db.query(Loan), Loan, library_id).all()
        data["loans"] = [
            {c.name: getattr(l, c.name) for c in Loan.__table__.columns}
            for l in loans
        ]

    return data


# ── EXPORT JSON ───────────────────────────────────────────────────────────────

@router.post("/export")
async def export_backup(
    include_books:   bool = True,
    include_members: bool = True,
    include_loans:   bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
    library_id: Optional[int] = Depends(get_library_id),
):
    """
    Preuzmi backup kao JSON datoteku.
    Admin knjižnice dobiva samo podatke svoje knjižnice.
    Globalni admin dobiva sve podatke.
    """
    data = _build_backup(
        db, library_id, current_user,
        include_books, include_members, include_loans,
    )

    lib_sfx = f"_lib{library_id}" if library_id else "_global"
    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname   = f"backup{lib_sfx}_{ts}.json"

    return Response(
        content=json.dumps(data, indent=2, ensure_ascii=False, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ── EXPORT ZIP ────────────────────────────────────────────────────────────────

@router.post("/export-zip")
async def export_backup_zip(
    include_books:   bool = True,
    include_members: bool = True,
    include_loans:   bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
    library_id: Optional[int] = Depends(get_library_id),
):
    """Preuzmi backup kao ZIP datoteku."""
    data = _build_backup(
        db, library_id, current_user,
        include_books, include_members, include_loans,
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "backup.json",
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
        )
    buf.seek(0)

    lib_sfx = f"_lib{library_id}" if library_id else "_global"
    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname   = f"backup{lib_sfx}_{ts}.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ── RESTORE ───────────────────────────────────────────────────────────────────

@router.post("/restore")
async def restore_backup(
    file: UploadFile = File(...),
    dry_run: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
    library_id: Optional[int] = Depends(get_library_id),
):
    """
    Restore iz uploadanog JSON ili ZIP backup fajla.

    - dry_run=true: samo provjeri kompatibilnost, ne uvozi podatke
    - Sigurnosna provjera: library_id iz backupa mora odgovarati
      library_id korisnika (ili korisnik mora biti globalni admin)
    """
    # Čitaj datoteku
    content = await file.read()
    try:
        if file.filename and file.filename.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                with zf.open("backup.json") as f:
                    backup_data = json.loads(f.read().decode("utf-8"))
        else:
            backup_data = json.loads(content.decode("utf-8"))
    except Exception as e:
        raise HTTPException(400, f"Nevalidna backup datoteka: {e}")

    # ── Multitenant sigurnosna provjera ──────────────────────────────────────
    bkp_lib_id = backup_data.get("library_id")
    if library_id is not None:  # Nije globalni admin
        if bkp_lib_id is not None and int(bkp_lib_id) != int(library_id):
            raise HTTPException(
                403,
                f"Backup je s knjižnice ID={bkp_lib_id}, "
                f"a vaša je ID={library_id}. Restore nije dozvoljen."
            )

    if dry_run:
        return {
            "status":       "dry_run_ok",
            "library_id":   bkp_lib_id,
            "library_name": backup_data.get("library_name"),
            "books_count":  len(backup_data.get("books", [])),
            "members_count": len(backup_data.get("members", [])),
            "loans_count":  len(backup_data.get("loans", [])),
            "created_at":   backup_data.get("created_at"),
            "version":      backup_data.get("version"),
        }

    # ── Dozvoljeni create-fields ──────────────────────────────────────────────
    BOOK_FIELDS = {
        "isbn", "title", "author", "publisher", "year", "genre",
        "shelf", "language", "series", "series_order", "tags",
        "total_copies", "description", "cover_url", "library_id",
    }
    MEMBER_FIELDS = {
        "first_name", "last_name", "email", "phone", "address",
        "joined_date", "is_active", "membership_number",
        "date_of_birth", "city", "country", "library_id",
    }
    LOAN_FIELDS = {
        "book_id", "member_id", "loan_date", "due_date", "notes",
        "is_returned", "return_date", "created_by",
        "loan_status", "renewal_count", "fine_amount", "library_id",
    }

    sc = {"books": 0, "members": 0, "loans": 0}
    ec = {"books": 0, "members": 0, "loans": 0}
    errors = []

    # ── Vrati knjige ─────────────────────────────────────────────────────────
    for i, book in enumerate(backup_data.get("books", [])):
        d = {k: v for k, v in book.items() if k in BOOK_FIELDS}
        # Uvijek postavi library_id na trenutnu knjižnicu
        if library_id is not None:
            d["library_id"] = library_id
        if not d.get("title") or not d.get("author"):
            ec["books"] += 1
            continue
        try:
            # Provjeri duplikat po ISBN-u ako postoji
            if d.get("isbn"):
                existing = db.query(Book).filter(Book.isbn == d["isbn"])
                if library_id:
                    existing = existing.filter(
                        Book.library_id == library_id)
                if existing.first():
                    sc["books"] += 1  # preskoči duplikat
                    continue
            obj = Book(**d)
            db.add(obj)
            sc["books"] += 1
        except Exception as e:
            ec["books"] += 1
            errors.append(f"Knjiga {i+1}: {str(e)[:80]}")

    # ── Vrati članove ────────────────────────────────────────────────────────
    for i, member in enumerate(backup_data.get("members", [])):
        d = {k: v for k, v in member.items() if k in MEMBER_FIELDS}
        if library_id is not None:
            d["library_id"] = library_id
        if not d.get("first_name") or not d.get("last_name"):
            ec["members"] += 1
            continue
        try:
            obj = Member(**d)
            db.add(obj)
            sc["members"] += 1
        except Exception as e:
            ec["members"] += 1
            errors.append(
                f"Član {i+1} ({d.get('first_name','')} "
                f"{d.get('last_name','')}): {str(e)[:80]}"
            )

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Greška pri commit-u: {e}")

    return {
        "status":        "restored" if sum(ec.values()) == 0 else "partial",
        "library_id":    library_id,
        "library_name":  backup_data.get("library_name"),
        "books_ok":      sc["books"],
        "books_err":     ec["books"],
        "members_ok":    sc["members"],
        "members_err":   ec["members"],
        "loans_ok":      sc["loans"],
        "loans_err":     ec["loans"],
        "errors":        errors[:20],
    }


# ── INFO ──────────────────────────────────────────────────────────────────────

@router.get("/info")
async def backup_info(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
    library_id: Optional[int] = Depends(get_library_id),
):
    """Vrati statistiku podataka za backup."""
    books_count   = _filter_by_lib(db.query(Book),   Book,   library_id).count()
    members_count = _filter_by_lib(db.query(Member), Member, library_id).count()
    loans_count   = _filter_by_lib(db.query(Loan),   Loan,   library_id).count()

    lib_name = None
    if library_id is not None:
        from app.models.library import Library
        lib = db.query(Library).filter(Library.id == library_id).first()
        lib_name = lib.name if lib else f"Library {library_id}"

    return {
        "library_id":     library_id,
        "library_name":   lib_name or "Sve knjižnice",
        "books_count":    books_count,
        "members_count":  members_count,
        "loans_count":    loans_count,
        "total":          books_count + members_count + loans_count,
    }
