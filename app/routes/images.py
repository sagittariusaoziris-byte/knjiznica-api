"""
Image management routes for Knjižnica API
Upravljanje slikama i naslovnicama knjiga.
"""

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiofiles
from app.database import get_db
from app.models.models import Book
from fastapi import (APIRouter, Depends, File, HTTPException, Query, Response,
                     UploadFile)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

router = APIRouter(prefix="/books/{book_id}/cover", tags=["Slike"])

# Konfiguracija
UPLOAD_DIR = "uploads/covers"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

# Kreiraj direktorij ako ne postoji
Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)


def get_cover_path(book_id: int) -> str:
    """Dohvati putanju do naslovnice knjige."""
    return os.path.join(UPLOAD_DIR, f"{book_id}")


def get_cover_thumbnail_path(book_id: int) -> str:
    """Dohvati putanju do thumbnaila naslovnice."""
    return os.path.join(UPLOAD_DIR, f"{book_id}_thumb")


@router.post("/upload")
async def upload_cover(
    book_id: int,
    file: UploadFile = File(..., description="Slika naslovnice (JPG, PNG, WebP, max 5MB)"),
    db: Session = Depends(get_db)
):
    """
    Upload naslovnice za knjigu.

    - **book_id**: ID knjige
    - **file**: Slika naslovnice (JPG, PNG, WebP, max 5MB)
    """
    # Provjeri postoji li knjiga
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")

    # Provjeri ekstenziju
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Nedozvoljen format. Dozvoljeni: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Provjeri veličinu
    file_data = await file.read()
    if len(file_data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Datoteka je prevelika (max 5MB)")

    # Spremi sliku
    cover_path = get_cover_path(book_id)
    async with aiofiles.open(cover_path, 'wb') as out_file:
        await out_file.write(file_data)

    # Ažuriraj cover_url u bazi
    timestamp = datetime.now().timestamp()
    cover_url = f"/api/books/{book_id}/cover?t={timestamp}"
    book.cover_url = cover_url
    db.commit()

    # Generiraj thumbnail (ako je potrebno)
    try:
        import io

        from PIL import Image

        image = Image.open(io.BytesIO(file_data))
        image.thumbnail((200, 300), Image.Resampling.LANCZOS)

        thumb_path = get_cover_thumbnail_path(book_id)
        image.save(thumb_path, format=image.format or 'JPEG')
    except ImportError:
        pass  # PIL nije instaliran, preskoči thumbnail
    except Exception:
        pass  # Greška pri generiranju thumbnaila

    return {
        "message": "Naslovnica uspješno učitana",
        "book_id": book_id,
        "cover_url": cover_url,
        "file_size": len(file_data),
        "file_type": file.content_type
    }


@router.get("/")
async def get_cover(
    book_id: int,
    thumbnail: Optional[bool] = Query(False, description="Vrati thumbnail umjesto pune slike"),
    db: Session = Depends(get_db)
):
    """
    Dohvati naslovnicu knjige.

    - **book_id**: ID knjige
    - **thumbnail**: Vrati thumbnail umjesto pune slike
    """
    # Provjeri postoji li knjiga
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")

    # Odaberi putanju
    if thumbnail:
        file_path = get_cover_thumbnail_path(book_id)
    else:
        file_path = get_cover_path(book_id)

    # Provjeri postoji li datoteka
    if not os.path.exists(file_path):
        # Pokušaj drugu putanju (bez thumbnaila)
        if thumbnail:
            file_path = get_cover_path(book_id)
            if not os.path.exists(file_path):
                raise HTTPException(status_code=404, detail="Naslovnica nije pronađena")
        else:
            raise HTTPException(status_code=404, detail="Naslovnica nije pronađena")

    # Dohvati ekstenziju i content type
    file_ext = os.path.splitext(file_path)[1].lower()
    content_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp"
    }
    content_type = content_types.get(file_ext, "image/jpeg")

    # Vrati sliku
    return FileResponse(
        file_path,
        media_type=content_type,
        filename=f"cover_{book_id}{file_ext}"
    )


@router.delete("/")
def delete_cover(
    book_id: int,
    db: Session = Depends(get_db)
):
    """
    Obriši naslovnicu knjige.

    - **book_id**: ID knjige
    """
    # Provjeri postoji li knjiga
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")

    # Obriši datoteke
    cover_path = get_cover_path(book_id)
    thumb_path = get_cover_thumbnail_path(book_id)

    deleted_files = []

    if os.path.exists(cover_path):
        os.remove(cover_path)
        deleted_files.append("cover")

    if os.path.exists(thumb_path):
        os.remove(thumb_path)
        deleted_files.append("thumbnail")

    # Ažuriraj cover_url u bazi
    book.cover_url = None
    db.commit()

    return {
        "message": "Naslovnica uspješno obrisana",
        "book_id": book_id,
        "deleted_files": deleted_files
    }


@router.get("/info")
def get_cover_info(
    book_id: int,
    db: Session = Depends(get_db)
):
    """
    Dohvati informacije o naslovnici knjige.

    - **book_id**: ID knjige
    """
    # Provjeri postoji li knjiga
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")

    cover_path = get_cover_path(book_id)
    thumb_path = get_cover_thumbnail_path(book_id)

    cover_exists = os.path.exists(cover_path)
    thumb_exists = os.path.exists(thumb_path)

    file_size = os.path.getsize(cover_path) if cover_exists else 0
    thumb_size = os.path.getsize(thumb_path) if thumb_exists else 0

    return {
        "book_id": book_id,
        "has_cover": cover_exists,
        "has_thumbnail": thumb_exists,
        "cover_url": book.cover_url,
        "file_size": file_size,
        "thumbnail_size": thumb_size,
        "cover_path": cover_path if cover_exists else None,
        "thumbnail_path": thumb_path if thumb_exists else None
    }


@router.post("/from-url")
async def upload_cover_from_url(
    book_id: int,
    url: str = Query(..., description="URL slike naslovnice"),
    db: Session = Depends(get_db)
):
    """
    Preuzmi i spremi naslovnicu s URL-a.

    - **book_id**: ID knjige
    - **url**: URL slike naslovnice
    """
    import urllib.request

    # Provjeri postoji li knjiga
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Knjiga nije pronađena")

    try:
        # Preuzmi sliku
        headers = {'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(url, headers=headers)

        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status != 200:
                raise HTTPException(status_code=400, detail="Neuspješno preuzimanje slike")

            content_type = response.headers.get('Content-Type', '')
            if not content_type.startswith('image/'):
                raise HTTPException(status_code=400, detail="URL ne vodi do slike")

            file_data = response.read()

            if len(file_data) > MAX_FILE_SIZE:
                raise HTTPException(status_code=400, detail="Slika je prevelika (max 5MB)")

        # Odredi ekstenziju iz content type
        ext_map = {
            'image/jpeg': '.jpg',
            'image/png': '.png',
            'image/webp': '.webp'
        }
        file_ext = ext_map.get(content_type.split(';')[0], '.jpg')

        # Spremi sliku
        cover_path = get_cover_path(book_id)
        async with aiofiles.open(cover_path, 'wb') as out_file:
            await out_file.write(file_data)

        # Ažuriraj cover_url u bazi
        timestamp = datetime.now().timestamp()
        cover_url = f"/api/books/{book_id}/cover?t={timestamp}"
        book.cover_url = cover_url
        db.commit()

        return {
            "message": "Naslovnica uspješno preuzeta s URL-a",
            "book_id": book_id,
            "cover_url": cover_url,
            "file_size": len(file_data),
            "source_url": url
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Greška pri preuzimanju: {str(e)}")


@router.get("/list")
def list_covers(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Lista svih knjiga s naslovnicama.

    - **skip**: Broj za preskakanje
    - **limit**: Maksimalni broj rezultata
    """
    books = db.query(Book).filter(Book.cover_url != None).offset(skip).limit(limit).all()

    result = []
    for book in books:
        cover_path = get_cover_path(book.id)
        has_cover = os.path.exists(cover_path)

        result.append({
            "book_id": book.id,
            "title": book.title,
            "author": book.author,
            "cover_url": book.cover_url,
            "has_cover_file": has_cover
        })

    return {
        "total": len(result),
        "skip": skip,
        "limit": limit,
        "books": result
    }
