"""
app/routes/pdf.py
VERZIJA: 9.0.0 — Server-side PDF generiranje (multi-tenant)

Endpointovi za generiranje PDF izvješća na serveru.
Svi endpointovi filtriraju po library_id iz JWT tokena.
"""
import io
import os
from datetime import date
from typing import List, Optional

from app.auth import get_library_id, require_staff
from app.database import get_db
from app.models.library import Library
from app.models.models import Book, Loan, Member
from app.models.user import User
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Spacer, Paragraph, Table, TableStyle
from sqlalchemy import or_
from sqlalchemy.orm import Session

router = APIRouter(prefix="/pdf", tags=["PDF Ispisi"])


# ══════════════════════════════════════════════════════════════════════════════
#  FONT REGISTRACIJA (hrvatska slova)
# ══════════════════════════════════════════════════════════════════════════════

def _register_fonts():
    """Registriraj font koji podržava hrvatska slova."""
    font_paths = [
        r"C:\Windows\Fonts\DejaVuSans.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("HRFont", path))
                return "HRFont"
            except Exception:
                continue
    return "Helvetica"


HR_FONT = _register_fonts()


# ══════════════════════════════════════════════════════════════════════════════
#  POMOĆNE FUNKCIJE
# ══════════════════════════════════════════════════════════════════════════════

def _get_library_info(db: Session, library_id: Optional[int]) -> dict:
    """Dohvati informacije o knjižnici za branding."""
    if library_id:
        lib = db.query(Library).filter(Library.id == library_id).first()
        if lib:
            return {
                "name": lib.name,
                "city": lib.city or "",
                "address": lib.address or "",
                "email": lib.email or "",
                "phone": lib.phone or "",
            }
    return {
        "name": "Knjižnica",
        "city": "",
        "address": "",
        "email": "",
        "phone": "",
    }


def _style(size=9, bold=False, color=None, alignment=0):
    """Kreiraj stil s hrvatskim fontom."""
    s = ParagraphStyle(
        name=f"hr_{size}_{bold}_{alignment}",
        fontName=HR_FONT,
        fontSize=size,
        leading=size + 3,
        alignment=alignment,
    )
    if color:
        s.textColor = color
    return s


def _table_style(header_color=None):
    """Standardni stil tablice."""
    hc = header_color or colors.HexColor("#1a1a2e")
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), hc),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), HR_FONT),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4f8")]),
        ("FONTNAME", (0, 1), (-1, -1), HR_FONT),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ])


def _build_pdf_response(elements, filename):
    """Izgradi PDF i vrati kao StreamingResponse."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm
    )
    doc.build(elements)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


def _add_header(elements, title, lib_info):
    """Dodaj zaglavlje s nazivom knjižnice."""
    lib_name = lib_info.get("name", "Knjižnica")
    elements.append(Paragraph(
        f"{lib_name} — {title}",
        _style(size=18, color=colors.HexColor("#1a1a2e"))
    ))
    elements.append(Paragraph(
        f"Generirano: {date.today().strftime('%d.%m.%Y.')}",
        _style(size=10, color=colors.HexColor("#666666"))
    ))
    elements.append(Spacer(1, 0.5 * cm))


def _add_footer(elements, count, label, lib_info):
    """Dodaj podnožje s brojem zapisa i brandingom."""
    lib_name = lib_info.get("name", "Knjižnica")
    elements.append(Spacer(1, 0.3 * cm))
    elements.append(Paragraph(
        f"Ukupno: {count} {label}  |  {lib_name}  |  Generirano: {date.today().strftime('%d.%m.%Y.')}",
        _style(size=8, color=colors.HexColor("#888888"))
    ))


# ══════════════════════════════════════════════════════════════════════════════
#  ENDPOINT: POPIS KNJIGA
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/books")
def pdf_books(
    search: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
    available_only: bool = False,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    """Generiraj PDF s popisom knjiga."""
    query = db.query(Book)
    if library_id is not None:
        query = query.filter(Book.library_id == library_id)
    if search:
        query = query.filter(or_(
            Book.title.ilike(f"%{search}%"),
            Book.author.ilike(f"%{search}%"),
            Book.isbn == search,
        ))
    if genre:
        query = query.filter(Book.genre == genre)
    if available_only:
        query = query.filter(Book.available_copies > 0)

    books = query.order_by(Book.title).all()
    lib_info = _get_library_info(db, library_id)

    elements = []
    _add_header(elements, "Popis knjiga", lib_info)

    headers = ["#", "Naslov", "Autor", "Zanr", "God.", "Ukupno", "Dostupno"]
    data = [headers]
    for i, b in enumerate(books, 1):
        data.append([
            str(i),
            str(b.title or "")[:40],
            str(b.author or "")[:25],
            str(b.genre or "-"),
            str(b.year or "-"),
            str(b.total_copies or 0),
            str(b.available_copies or 0),
        ])

    col_widths = [1 * cm, 6.5 * cm, 4.5 * cm, 2.5 * cm, 1.5 * cm, 1.8 * cm, 1.8 * cm]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(_table_style())
    elements.append(table)
    _add_footer(elements, len(books), "knjiga", lib_info)

    return _build_pdf_response(elements, "popis_knjiga.pdf")


# ══════════════════════════════════════════════════════════════════════════════
#  ENDPOINT: POPIS CLANOVA
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/members")
def pdf_members(
    search: Optional[str] = Query(None),
    active_only: bool = False,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    """Generiraj PDF s popisom clanova."""
    query = db.query(Member)
    if library_id is not None:
        query = query.filter(Member.library_id == library_id)
    if search:
        query = query.filter(or_(
            Member.first_name.ilike(f"%{search}%"),
            Member.last_name.ilike(f"%{search}%"),
            Member.email.ilike(f"%{search}%"),
        ))
    if active_only:
        query = query.filter(Member.is_active == True)

    members = query.order_by(Member.last_name, Member.first_name).all()
    lib_info = _get_library_info(db, library_id)

    elements = []
    _add_header(elements, "Popis clanova", lib_info)

    headers = ["#", "Broj clana", "Ime i prezime", "Email", "Telefon", "Aktivan"]
    data = [headers]
    for i, m in enumerate(members, 1):
        data.append([
            str(i),
            str(m.member_number or ""),
            f"{m.first_name or ''} {m.last_name or ''}",
            str(m.email or "-"),
            str(m.phone or "-"),
            "Da" if m.is_active else "Ne",
        ])

    col_widths = [0.8 * cm, 2.5 * cm, 4.5 * cm, 4.5 * cm, 2.8 * cm, 1.8 * cm]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(_table_style())
    elements.append(table)
    _add_footer(elements, len(members), "clanova", lib_info)

    return _build_pdf_response(elements, "popis_clanova.pdf")


# ══════════════════════════════════════════════════════════════════════════════
#  ENDPOINT: POPIS POSUDBI
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/loans")
def pdf_loans(
    active_only: bool = False,
    overdue_only: bool = False,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    """Generiraj PDF s popisom posudbi."""
    query = db.query(Loan).join(Book).join(Member)
    if library_id is not None:
        query = query.filter(Loan.library_id == library_id)
    if active_only:
        query = query.filter(Loan.is_returned == False)
    if overdue_only:
        today = date.today()
        query = query.filter(Loan.is_returned == False, Loan.due_date < today)

    loans = query.order_by(Loan.loan_date.desc()).all()
    lib_info = _get_library_info(db, library_id)

    elements = []
    title = "Prekoracene posudbe" if overdue_only else ("Aktivne posudbe" if active_only else "Popis posudbi")
    _add_header(elements, title, lib_info)

    headers = ["#", "Knjiga", "Clan", "Datum posudbe", "Rok vracanja", "Status"]
    data = [headers]
    today = date.today()
    for i, loan in enumerate(loans, 1):
        due = loan.due_date
        if loan.is_returned:
            status = "Vraceno"
        elif due and due < today:
            status = f"Kasni {(today - due).days}d"
        else:
            status = "Aktivno"

        book_title = loan.book.title if loan.book else "-"
        member_name = f"{loan.member.first_name or ''} {loan.member.last_name or ''}" if loan.member else "-"

        data.append([
            str(i),
            str(book_title)[:30],
            str(member_name)[:25],
            str(loan.loan_date or "-"),
            str(loan.due_date or "-"),
            status,
        ])

    col_widths = [0.8 * cm, 5 * cm, 4 * cm, 2.8 * cm, 2.8 * cm, 2.5 * cm]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(_table_style())
    elements.append(table)
    _add_footer(elements, len(loans), "posudbi", lib_info)

    return _build_pdf_response(elements, "popis_posudbi.pdf")


# ══════════════════════════════════════════════════════════════════════════════
#  ENDPOINT: CLANSKI KARTON
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/member-card/{member_id}")
def pdf_member_card(
    member_id: int,
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    """Generiraj detaljan clanski karton s posudbama."""
    query = db.query(Member)
    if library_id is not None:
        query = query.filter(Member.library_id == library_id)
    member = query.filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Clan nije pronadjen")

    # Dohvati posudbe clana
    loans_query = db.query(Loan).join(Book).filter(Loan.member_id == member_id)
    if library_id is not None:
        loans_query = loans_query.filter(Loan.library_id == library_id)
    loans = loans_query.order_by(Loan.loan_date.desc()).all()

    lib_info = _get_library_info(db, library_id)

    elements = []
    lib_name = lib_info.get("name", "Knjižnica")
    elements.append(Paragraph(
        f"{lib_name} — Clanski karton",
        _style(size=18, color=colors.HexColor("#1a1a2e"))
    ))
    elements.append(Spacer(1, 0.3 * cm))

    # Osobni podaci
    full_name = f"{member.first_name or ''} {member.last_name or ''}"
    info_data = [
        ["Broj clana:", member.member_number or "-"],
        ["Ime i prezime:", full_name],
        ["Email:", member.email or "-"],
        ["Telefon:", member.phone or "-"],
        ["Adresa:", member.address or "-"],
        ["Status:", "AKTIVAN" if member.is_active else "NEAKTIVAN"],
    ]

    info_table = Table(info_data, colWidths=[4.5 * cm, 12 * cm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), HR_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#666666")),
        ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR", (1, 5), (1, 5),
         colors.HexColor("#27ae60") if member.is_active else colors.HexColor("#e74c3c")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#eeeeee")),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 0.5 * cm))

    # Statistike
    today = date.today()
    all_loans = loans
    active_loans = [l for l in all_loans if not l.is_returned]
    returned_loans = [l for l in all_loans if l.is_returned]
    overdue_loans = [l for l in active_loans if l.due_date and l.due_date < today]

    stat_data = [
        ["Ukupno posudjeno:", str(len(all_loans)), "knjiga"],
        ["Trenutno aktivnih:", str(len(active_loans)), "knjiga"],
        ["Vraceno:", str(len(returned_loans)), "knjiga"],
        ["Prekoracenih:", str(len(overdue_loans)), "knjiga"],
    ]

    stat_table = Table(stat_data, colWidths=[7 * cm, 2.5 * cm, 7 * cm])
    stat_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), HR_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
        ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#1a6b9a")),
        ("FONTSIZE", (1, 0), (1, -1), 13),
        ("TEXTCOLOR", (1, 3), (1, 3),
         colors.HexColor("#e74c3c") if overdue_loans else colors.HexColor("#27ae60")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
    ]))
    elements.append(stat_table)
    elements.append(Spacer(1, 0.5 * cm))

    # Aktivne posudbe
    if active_loans:
        elements.append(Paragraph(
            f"AKTIVNE POSUDBE ({len(active_loans)})",
            _style(size=11, color=colors.HexColor("#2c3e50"))
        ))
        headers = ["#", "Naslov knjige", "Autor", "Datum posudbe", "Rok vracanja", "Status"]
        loan_data = [headers]
        for i, loan in enumerate(active_loans, 1):
            due = loan.due_date
            days_left = (due - today).days if due else 0
            if days_left < 0:
                status = f"Kasni {abs(days_left)}d"
            elif days_left == 0:
                status = "Danas!"
            else:
                status = f"Jos {days_left}d"

            book_title = loan.book.title if loan.book else "-"
            book_author = loan.book.author if loan.book else "-"

            loan_data.append([
                str(i),
                str(book_title)[:28],
                str(book_author)[:20],
                str(loan.loan_date or "-"),
                str(loan.due_date or "-"),
                status,
            ])

        loan_table = Table(loan_data, colWidths=[0.7 * cm, 5.2 * cm, 3.5 * cm, 2.5 * cm, 2.5 * cm, 2.1 * cm], repeatRows=1)
        ts = _table_style(header_color=colors.HexColor("#2c3e50"))
        for i, loan in enumerate(active_loans, 1):
            if loan.due_date and loan.due_date < today:
                ts.add("TEXTCOLOR", (5, i), (5, i), colors.HexColor("#e74c3c"))
        loan_table.setStyle(ts)
        elements.append(loan_table)
        elements.append(Spacer(1, 0.4 * cm))

    # Povijest vracenih
    if returned_loans:
        recent = returned_loans[-10:]
        elements.append(Paragraph(
            f"POVIJEST POSUDBI (zadnjih {len(recent)})",
            _style(size=11, color=colors.HexColor("#2c3e50"))
        ))
        hist_headers = ["#", "Naslov knjige", "Autor", "Datum posudbe", "Vraceno"]
        hist_data = [hist_headers]
        for i, loan in enumerate(reversed(recent), 1):
            book_title = loan.book.title if loan.book else "-"
            book_author = loan.book.author if loan.book else "-"
            hist_data.append([
                str(i),
                str(book_title)[:30],
                str(book_author)[:22],
                str(loan.loan_date or "-"),
                str(loan.return_date or "-"),
            ])
        hist_table = Table(hist_data, colWidths=[0.7 * cm, 5.8 * cm, 4 * cm, 2.8 * cm, 2.8 * cm], repeatRows=1)
        hist_table.setStyle(_table_style(header_color=colors.HexColor("#555555")))
        elements.append(hist_table)

    elements.append(Spacer(1, 0.3 * cm))
    elements.append(Paragraph(
        f"{lib_name}  |  Generirano: {today.strftime('%d.%m.%Y.')}  |  Broj clana: {member.member_number or '-'}",
        _style(size=8, color=colors.HexColor("#888888"), alignment=1)
    ))

    return _build_pdf_response(elements, f"clanski_karton_{member.member_number}.pdf")


# ══════════════════════════════════════════════════════════════════════════════
#  ENDPOINT: INVENTURNA LISTA
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/inventory")
def pdf_inventory(
    genre: Optional[str] = Query(None),
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    """Generiraj inventurnu listu knjiga."""
    query = db.query(Book)
    if library_id is not None:
        query = query.filter(Book.library_id == library_id)
    if genre:
        query = query.filter(Book.genre == genre)

    books = query.order_by(Book.genre, Book.title).all()
    lib_info = _get_library_info(db, library_id)

    elements = []
    _add_header(elements, "Inventurna lista", lib_info)

    headers = ["#", "Inventarni br.", "Naslov", "Autor", "Zanr", "God.", "Primjeraka", "Potpis"]
    data = [headers]
    for i, b in enumerate(books, 1):
        data.append([
            str(i),
            str(b.isbn or "-"),
            str(b.title or "")[:35],
            str(b.author or "")[:25],
            str(b.genre or "-"),
            str(b.year or "-"),
            str(b.total_copies or 0),
            "",
        ])

    col_widths = [0.7 * cm, 2.5 * cm, 5 * cm, 3.5 * cm, 2 * cm, 1.3 * cm, 1.8 * cm, 2.2 * cm]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(_table_style())
    elements.append(table)
    _add_footer(elements, len(books), "knjiga", lib_info)

    return _build_pdf_response(elements, "inventurna_lista.pdf")


# ══════════════════════════════════════════════════════════════════════════════
#  ENDPOINT: OBAVIJESTI O KASNJENJU
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/overdue-notices")
def pdf_overdue_notices(
    library_id: Optional[int] = Depends(get_library_id),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    """Generiraj obavijesti o kasnjenju za tiskanje i slanje."""
    today = date.today()
    query = db.query(Loan).join(Book).join(Member).filter(
        Loan.is_returned == False,
        Loan.due_date < today
    )
    if library_id is not None:
        query = query.filter(Loan.library_id == library_id)

    loans = query.order_by(Member.last_name, Member.first_name).all()
    lib_info = _get_library_info(db, library_id)

    elements = []
    lib_name = lib_info.get("name", "Knjižnica")

    # Grupiraj po clanovima
    from collections import defaultdict
    member_loans = defaultdict(list)
    for loan in loans:
        member_loans[loan.member_id].append(loan)

    for member_id, mloans in member_loans.items():
        member = mloans[0].member
        if not member:
            continue

        full_name = f"{member.first_name or ''} {member.last_name or ''}"

        elements.append(Paragraph(
            f"{lib_name}",
            _style(size=16, color=colors.HexColor("#1a1a2e"), alignment=1)
        ))
        elements.append(Paragraph(
            "OBAVIJEST O PREKORACENOM ROKU VRACANJA KNJIGE",
            _style(size=12, color=colors.HexColor("#c0392b"), alignment=1)
        ))
        elements.append(Spacer(1, 0.5 * cm))

        elements.append(Paragraph(
            f"Postovani/a <b>{full_name}</b>,",
            _style(size=10)
        ))
        elements.append(Paragraph(
            "Podsjecamo Vas da imate sljedece prekoracene posudbe:",
            _style(size=10)
        ))
        elements.append(Spacer(1, 0.3 * cm))

        headers = ["Naslov knjige", "Datum posudbe", "Rok vracanja", "Dana kasni"]
        data = [headers]
        for loan in mloans:
            due = loan.due_date
            days_late = (today - due).days if due else 0
            book_title = loan.book.title if loan.book else "-"
            data.append([
                str(book_title)[:35],
                str(loan.loan_date or "-"),
                str(loan.due_date or "-"),
                f"{days_late} dana",
            ])

        table = Table(data, colWidths=[6 * cm, 3 * cm, 3 * cm, 2.5 * cm], repeatRows=1)
        table.setStyle(_table_style(header_color=colors.HexColor("#c0392b")))
        elements.append(table)
        elements.append(Spacer(1, 0.5 * cm))

        elements.append(Paragraph(
            "Molimo Vas da sto prije vratite navedene knjige ili kontaktirate knjiznicu.",
            _style(size=10)
        ))
        if lib_info.get("phone"):
            elements.append(Paragraph(
                f"Telefon: {lib_info['phone']}",
                _style(size=10)
            ))
        if lib_info.get("email"):
            elements.append(Paragraph(
                f"Email: {lib_info['email']}",
                _style(size=10)
            ))
        elements.append(Spacer(1, 0.3 * cm))
        elements.append(Paragraph(
            f"Generirano: {today.strftime('%d.%m.%Y.')}  |  {lib_name}",
            _style(size=8, color=colors.HexColor("#888888"), alignment=1)
        ))

        # Novi list za sljedeceg clana
        elements.append(Paragraph("<pagebreak/>", _style(size=1)))

    return _build_pdf_response(elements, "obavijesti_kasnjenje.pdf")
