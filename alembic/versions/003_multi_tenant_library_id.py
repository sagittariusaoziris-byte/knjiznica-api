"""multi_tenant_library_id

Revision ID: 003_multi_tenant
Revises: 002_add_license_v860_columns
Create Date: 2026-04-25

VERZIJA 9.0.0 — Multi-tenant migracija (Opcija A)

Što radi:
  1. Kreira tablicu 'libraries' s 4 knjižnice
  2. Dodaje library_id u: books, members, loans, reservations,
     ratings, notifications, users
  3. Postavlja default library_id=1 za postojeće podatke
  4. Dodaje indekse za performanse
  5. Uklanja stare globalne unique constrainte (isbn, member_number)
  6. Dodaje nove composite unique constrainte po knjižnici

VAŽNO: Pokreni PRIJE deploy-a nove verzije koda.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = "003_multi_tenant"
down_revision: Union[str, None] = "002_add_license_v860_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. Kreiraj tablicu libraries ─────────────────────────────────────────
    op.create_table(
        "libraries",
        sa.Column("id",         sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column("name",       sa.String(128),   nullable=False),
        sa.Column("slug",       sa.String(64),    nullable=False, unique=True),
        sa.Column("city",       sa.String(64),    nullable=True),
        sa.Column("address",    sa.String(255),   nullable=True),
        sa.Column("email",      sa.String(128),   nullable=True),
        sa.Column("phone",      sa.String(32),    nullable=True),
        sa.Column("is_active",  sa.Boolean(),     nullable=False, server_default="1"),
        sa.Column("notes",      sa.Text(),        nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ── 2. Umetni 4 knjižnice ─────────────────────────────────────────────────
    conn.execute(text("""
        INSERT INTO libraries (id, name, slug, city, is_active)
        VALUES
            (1, 'Knjižnica Bugojno',  'bugojno',  'Bugojno',  true),
            (2, 'Knjižnica Sarajevo', 'sarajevo', 'Sarajevo', true),
            (3, 'Knjižnica Mostar',   'mostar',   'Mostar',   true),
            (4, 'Knjižnica Zenica',   'zenica',   'Zenica',   true)
    """))

    # ── 3. Dodaj library_id u books ───────────────────────────────────────────
    op.add_column("books", sa.Column("library_id", sa.Integer(), nullable=True))
    conn.execute(text("UPDATE books SET library_id = 1 WHERE library_id IS NULL"))
    op.alter_column("books", "library_id", nullable=False)
    op.create_index("ix_books_library_id", "books", ["library_id"])
    op.create_foreign_key("fk_books_library", "books", "libraries", ["library_id"], ["id"])

    # Ukloni stari global unique na isbn, dodaj composite
    try:
        op.drop_index("ix_books_isbn", table_name="books")
    except Exception:
        pass
    try:
        op.drop_constraint("books_isbn_key", "books", type_="unique")
    except Exception:
        pass
    op.create_unique_constraint("uq_book_library_isbn", "books", ["library_id", "isbn"])

    # ── 4. Dodaj library_id u members ─────────────────────────────────────────
    op.add_column("members", sa.Column("library_id", sa.Integer(), nullable=True))
    conn.execute(text("UPDATE members SET library_id = 1 WHERE library_id IS NULL"))
    op.alter_column("members", "library_id", nullable=False)
    op.create_index("ix_members_library_id", "members", ["library_id"])
    op.create_foreign_key("fk_members_library", "members", "libraries", ["library_id"], ["id"])

    # Composite unique za member_number
    try:
        op.drop_constraint("members_member_number_key", "members", type_="unique")
    except Exception:
        pass
    op.create_unique_constraint("uq_member_library_number", "members", ["library_id", "member_number"])

    # ── 5. Dodaj library_id u loans ───────────────────────────────────────────
    op.add_column("loans", sa.Column("library_id", sa.Integer(), nullable=True))
    conn.execute(text("UPDATE loans SET library_id = 1 WHERE library_id IS NULL"))
    op.alter_column("loans", "library_id", nullable=False)
    op.create_index("ix_loans_library_id", "loans", ["library_id"])
    op.create_foreign_key("fk_loans_library", "loans", "libraries", ["library_id"], ["id"])

    # ── 6. Dodaj library_id u reservations ────────────────────────────────────
    op.add_column("reservations", sa.Column("library_id", sa.Integer(), nullable=True))
    conn.execute(text("UPDATE reservations SET library_id = 1 WHERE library_id IS NULL"))
    op.alter_column("reservations", "library_id", nullable=False)
    op.create_index("ix_reservations_library_id", "reservations", ["library_id"])
    op.create_foreign_key("fk_reservations_library", "reservations", "libraries", ["library_id"], ["id"])

    # ── 7. Dodaj library_id u ratings ─────────────────────────────────────────
    op.add_column("ratings", sa.Column("library_id", sa.Integer(), nullable=True))
    conn.execute(text("UPDATE ratings SET library_id = 1 WHERE library_id IS NULL"))
    op.create_index("ix_ratings_library_id", "ratings", ["library_id"])
    op.create_foreign_key("fk_ratings_library", "ratings", "libraries", ["library_id"], ["id"])

    # ── 8. Dodaj library_id u notifications ───────────────────────────────────
    op.add_column("notifications", sa.Column("library_id", sa.Integer(), nullable=True))
    op.create_index("ix_notifications_library_id", "notifications", ["library_id"])

    # ── 9. Dodaj library_id u users ───────────────────────────────────────────
    op.add_column("users", sa.Column("library_id", sa.Integer(), nullable=True))
    op.create_index("ix_users_library_id", "users", ["library_id"])
    op.create_foreign_key("fk_users_library", "users", "libraries", ["library_id"], ["id"])

    # Postavi library_id=1 za sve postojeće korisnike OSIM admin-a
    conn.execute(text("""
        UPDATE users SET library_id = 1
        WHERE library_id IS NULL AND role != 'admin'
    """))

    # ── 10. Dodaj library_id u book_ratings ───────────────────────────────────
    try:
        op.add_column("book_ratings", sa.Column("library_id", sa.Integer(), nullable=True))
        op.create_index("ix_book_ratings_library_id", "book_ratings", ["library_id"])
    except Exception:
        pass  # Tablica možda ne postoji na svim instalacijama


def downgrade() -> None:
    # Ukloni sve library_id stupce i tablicu
    for table in ["book_ratings", "users", "notifications", "ratings",
                  "reservations", "loans", "members", "books"]:
        try:
            op.drop_index(f"ix_{table}_library_id", table_name=table)
        except Exception:
            pass
        try:
            op.drop_constraint(f"fk_{table}_library", table, type_="foreignkey")
        except Exception:
            pass
        try:
            op.drop_column(table, "library_id")
        except Exception:
            pass

    try:
        op.drop_constraint("uq_book_library_isbn", "books", type_="unique")
        op.drop_constraint("uq_member_library_number", "members", type_="unique")
    except Exception:
        pass

    op.drop_table("libraries")
