"""fresh_db_fix — idempotentna migracija za potpuno novu bazu

Revision ID: 005_fresh_db_fix
Revises: 004_initial_schema
Create Date: 2026-04-30

PROBLEM koji rješava:
  Na potpuno novoj Supabase bazi (praznoj), migracija 003 pada jer pokušava
  ALTER TABLE na tablicama (books, members, loans...) koje još ne postoje.
  004 pretpostavlja da libraries postoji (kreira je 003), pa i ona pada.
  Rezultat: 'libraries' tablica nikad nije kreirana, seed puca.

RJEŠENJE:
  Ova migracija kreira SVE što nedostaje — idempotentno (IF NOT EXISTS).
  Sigurna je i na staroj bazi (gdje sve već postoji) i na novoj (praznoj).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision: str = "005_fresh_db_fix"
down_revision: Union[str, None] = "004_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _column_exists(table: str, column: str) -> bool:
    if not _table_exists(table):
        return False
    return any(c["name"] == column for c in inspect(op.get_bind()).get_columns(table))


def _index_exists(index_name: str, table_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    indexes = inspect(op.get_bind()).get_indexes(table_name)
    return any(idx["name"] == index_name for idx in indexes)


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. libraries (može nedostajati ako je 003 pala) ──────────────────────
    if not _table_exists("libraries"):
        op.create_table(
            "libraries",
            sa.Column("id",         sa.Integer(),    primary_key=True, autoincrement=True),
            sa.Column("name",       sa.String(128),  nullable=False),
            sa.Column("slug",       sa.String(64),   nullable=False, unique=True),
            sa.Column("city",       sa.String(64),   nullable=True),
            sa.Column("address",    sa.String(255),  nullable=True),
            sa.Column("email",      sa.String(128),  nullable=True),
            sa.Column("phone",      sa.String(32),   nullable=True),
            sa.Column("is_active",  sa.Boolean(),    nullable=False, server_default="1"),
            sa.Column("notes",      sa.Text(),       nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
        conn.execute(text("""
            INSERT INTO libraries (id, name, slug, city, is_active)
            VALUES
                (1, 'Knjižnica Bugojno',  'bugojno',  'Bugojno',  true),
                (2, 'Knjižnica Sarajevo', 'sarajevo', 'Sarajevo', true),
                (3, 'Knjižnica Mostar',   'mostar',   'Mostar',   true),
                (4, 'Knjižnica Zenica',   'zenica',   'Zenica',   true)
        """))
        print("✓ Kreirana tablica 'libraries' s 4 knjižnice")

    # ── 2. users ─────────────────────────────────────────────────────────────
    if not _table_exists("users"):
        op.create_table(
            "users",
            sa.Column("id",              sa.Integer(),   primary_key=True, autoincrement=True),
            sa.Column("username",        sa.String(64),  nullable=False, unique=True),
            sa.Column("full_name",       sa.String(128), nullable=True),
            sa.Column("hashed_password", sa.String(256), nullable=False),
            sa.Column("plain_password",  sa.String(128), nullable=True),
            sa.Column("role",            sa.String(32),  nullable=False, server_default="knjiznicar"),
            sa.Column("library_id",      sa.Integer(),   sa.ForeignKey("libraries.id"), nullable=True),
            sa.Column("is_active",       sa.Boolean(),   nullable=False, server_default="1"),
            sa.Column("created_at",      sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
        if not _index_exists("ix_users_id", "users"):
            op.create_index("ix_users_id",       "users", ["id"])
        if not _index_exists("ix_users_username", "users"):
            op.create_index("ix_users_username", "users", ["username"], unique=True)
        if not _index_exists("ix_users_library_id", "users"):
            op.create_index("ix_users_library_id", "users", ["library_id"])
        print("✓ Kreirana tablica 'users'")
    else:
        # users postoji — samo dodaj library_id ako nedostaje
        if not _column_exists("users", "library_id"):
            op.add_column("users", sa.Column("library_id", sa.Integer(),
                sa.ForeignKey("libraries.id"), nullable=True))
            if not _index_exists("ix_users_library_id", "users"):
                op.create_index("ix_users_library_id", "users", ["library_id"])

    # ── 3. books ─────────────────────────────────────────────────────────────
    if not _table_exists("books"):
        op.create_table(
            "books",
            sa.Column("id",               sa.Integer(),  primary_key=True, autoincrement=True),
            sa.Column("library_id",       sa.Integer(),  sa.ForeignKey("libraries.id"), nullable=False),
            sa.Column("isbn",             sa.String(32), nullable=True),
            sa.Column("title",            sa.String(256),nullable=False),
            sa.Column("author",           sa.String(256),nullable=False),
            sa.Column("publisher",        sa.String(128),nullable=True),
            sa.Column("year",             sa.Integer(),  nullable=True),
            sa.Column("genre",            sa.String(64), nullable=True),
            sa.Column("shelf",            sa.String(32), nullable=True),
            sa.Column("language",         sa.String(8),  nullable=True, server_default="hr"),
            sa.Column("series",           sa.String(128),nullable=True),
            sa.Column("series_order",     sa.Integer(),  nullable=True),
            sa.Column("tags",             sa.String(512),nullable=True),
            sa.Column("total_copies",     sa.Integer(),  nullable=False, server_default="1"),
            sa.Column("available_copies", sa.Integer(),  nullable=False, server_default="1"),
            sa.Column("description",      sa.Text(),     nullable=True),
            sa.Column("cover_url",        sa.String(512),nullable=True),
            sa.Column("created_at",       sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.UniqueConstraint("library_id", "isbn", name="uq_book_library_isbn"),
        )
        if not _index_exists("ix_books_id", "books"):
            op.create_index("ix_books_id",         "books", ["id"])
        if not _index_exists("ix_books_title", "books"):
            op.create_index("ix_books_title",      "books", ["title"])
        if not _index_exists("ix_books_isbn", "books"):
            op.create_index("ix_books_isbn",       "books", ["isbn"])
        if not _index_exists("ix_books_library_id", "books"):
            op.create_index("ix_books_library_id", "books", ["library_id"])
        print("✓ Kreirana tablica 'books'")
    else:
        if not _column_exists("books", "library_id"):
            op.add_column("books", sa.Column("library_id", sa.Integer(),
                sa.ForeignKey("libraries.id"), nullable=True))
            conn.execute(text("UPDATE books SET library_id = 1 WHERE library_id IS NULL"))
            op.alter_column("books", "library_id", nullable=False)
            if not _index_exists("ix_books_library_id", "books"):
                op.create_index("ix_books_library_id", "books", ["library_id"])

    # ── 4. members ───────────────────────────────────────────────────────────
    if not _table_exists("members"):
        op.create_table(
            "members",
            sa.Column("id",            sa.Integer(),  primary_key=True, autoincrement=True),
            sa.Column("library_id",    sa.Integer(),  sa.ForeignKey("libraries.id"), nullable=False),
            sa.Column("member_number", sa.String(32), nullable=False),
            sa.Column("first_name",    sa.String(64), nullable=False),
            sa.Column("last_name",     sa.String(64), nullable=False),
            sa.Column("email",         sa.String(128),nullable=True),
            sa.Column("phone",         sa.String(32), nullable=True),
            sa.Column("address",       sa.String(256),nullable=True),
            sa.Column("is_active",     sa.Boolean(),  nullable=False, server_default="1"),
            sa.Column("joined_date",   sa.Date(),     nullable=True),
            sa.Column("created_at",    sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.UniqueConstraint("library_id", "member_number", name="uq_member_library_number"),
        )
        if not _index_exists("ix_members_id", "members"):
            op.create_index("ix_members_id",            "members", ["id"])
        if not _index_exists("ix_members_member_number", "members"):
            op.create_index("ix_members_member_number", "members", ["member_number"])
        if not _index_exists("ix_members_email", "members"):
            op.create_index("ix_members_email",         "members", ["email"])
        if not _index_exists("ix_members_library_id", "members"):
            op.create_index("ix_members_library_id",    "members", ["library_id"])
        print("✓ Kreirana tablica 'members'")
    else:
        if not _column_exists("members", "library_id"):
            op.add_column("members", sa.Column("library_id", sa.Integer(),
                sa.ForeignKey("libraries.id"), nullable=True))
            conn.execute(text("UPDATE members SET library_id = 1 WHERE library_id IS NULL"))
            op.alter_column("members", "library_id", nullable=False)
            if not _index_exists("ix_members_library_id", "members"):
                op.create_index("ix_members_library_id", "members", ["library_id"])

    # ── 5. loans ─────────────────────────────────────────────────────────────
    if not _table_exists("loans"):
        op.create_table(
            "loans",
            sa.Column("id",          sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("library_id",  sa.Integer(), sa.ForeignKey("libraries.id"), nullable=False),
            sa.Column("book_id",     sa.Integer(), sa.ForeignKey("books.id"),     nullable=False),
            sa.Column("member_id",   sa.Integer(), sa.ForeignKey("members.id"),   nullable=False),
            sa.Column("loan_date",   sa.Date(),    nullable=False),
            sa.Column("due_date",    sa.Date(),    nullable=False),
            sa.Column("return_date", sa.Date(),    nullable=True),
            sa.Column("is_returned", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("notes",       sa.Text(),    nullable=True),
            sa.Column("created_at",  sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at",  sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
        if not _index_exists("ix_loans_id", "loans"):
            op.create_index("ix_loans_id",         "loans", ["id"])
        if not _index_exists("ix_loans_library_id", "loans"):
            op.create_index("ix_loans_library_id", "loans", ["library_id"])
        print("✓ Kreirana tablica 'loans'")
    else:
        if not _column_exists("loans", "library_id"):
            op.add_column("loans", sa.Column("library_id", sa.Integer(),
                sa.ForeignKey("libraries.id"), nullable=True))
            conn.execute(text("UPDATE loans SET library_id = 1 WHERE library_id IS NULL"))
            op.alter_column("loans", "library_id", nullable=False)
            if not _index_exists("ix_loans_library_id", "loans"):
                op.create_index("ix_loans_library_id", "loans", ["library_id"])

    # ── 6. reservations ──────────────────────────────────────────────────────
    if not _table_exists("reservations"):
        op.create_table(
            "reservations",
            sa.Column("id",          sa.Integer(),  primary_key=True, autoincrement=True),
            sa.Column("library_id",  sa.Integer(),  sa.ForeignKey("libraries.id"), nullable=False),
            sa.Column("book_id",     sa.Integer(),  sa.ForeignKey("books.id"),     nullable=False),
            sa.Column("member_id",   sa.Integer(),  sa.ForeignKey("members.id"),   nullable=False),
            sa.Column("reserved_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_active",   sa.Boolean(),  nullable=False, server_default="1"),
        )
        if not _index_exists("ix_reservations_id", "reservations"):
            op.create_index("ix_reservations_id",         "reservations", ["id"])
        if not _index_exists("ix_reservations_library_id", "reservations"):
            op.create_index("ix_reservations_library_id", "reservations", ["library_id"])
        print("✓ Kreirana tablica 'reservations'")
    else:
        if not _column_exists("reservations", "library_id"):
            op.add_column("reservations", sa.Column("library_id", sa.Integer(),
                sa.ForeignKey("libraries.id"), nullable=True))
            conn.execute(text("UPDATE reservations SET library_id = 1 WHERE library_id IS NULL"))
            op.alter_column("reservations", "library_id", nullable=False)
            if not _index_exists("ix_reservations_library_id", "reservations"):
                op.create_index("ix_reservations_library_id", "reservations", ["library_id"])

    # ── 7. ratings ───────────────────────────────────────────────────────────
    if not _table_exists("ratings"):
        op.create_table(
            "ratings",
            sa.Column("id",         sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("library_id", sa.Integer(), sa.ForeignKey("libraries.id"), nullable=False),
            sa.Column("book_id",    sa.Integer(), sa.ForeignKey("books.id"),     nullable=False),
            sa.Column("member_id",  sa.Integer(), sa.ForeignKey("members.id"),   nullable=False),
            sa.Column("rating",     sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
        if not _index_exists("ix_ratings_id", "ratings"):
            op.create_index("ix_ratings_id",         "ratings", ["id"])
        if not _index_exists("ix_ratings_library_id", "ratings"):
            op.create_index("ix_ratings_library_id", "ratings", ["library_id"])
        print("✓ Kreirana tablica 'ratings'")

    # ── 8. notifications ─────────────────────────────────────────────────────
    if not _table_exists("notifications"):
        op.create_table(
            "notifications",
            sa.Column("id",         sa.Integer(),   primary_key=True, autoincrement=True),
            sa.Column("user_id",    sa.Integer(),   sa.ForeignKey("users.id"), nullable=True),
            sa.Column("library_id", sa.Integer(),   nullable=True),
            sa.Column("type",       sa.String(32),  nullable=False, server_default="system"),
            sa.Column("priority",   sa.String(16),  nullable=False, server_default="normal"),
            sa.Column("title",      sa.String(256), nullable=False),
            sa.Column("message",    sa.Text(),      nullable=False),
            sa.Column("is_read",    sa.Boolean(),   nullable=False, server_default="0"),
            sa.Column("data",       sa.Text(),      nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
        if not _index_exists("ix_notifications_id", "notifications"):
            op.create_index("ix_notifications_id",         "notifications", ["id"])
        if not _index_exists("ix_notifications_library_id", "notifications"):
            op.create_index("ix_notifications_library_id", "notifications", ["library_id"])
        print("✓ Kreirana tablica 'notifications'")
    else:
        if not _column_exists("notifications", "library_id"):
            op.add_column("notifications", sa.Column("library_id", sa.Integer(), nullable=True))
            if not _index_exists("ix_notifications_library_id", "notifications"):
                op.create_index("ix_notifications_library_id", "notifications", ["library_id"])

    # ── 9. book_ratings ──────────────────────────────────────────────────────
    if not _table_exists("book_ratings"):
        op.create_table(
            "book_ratings",
            sa.Column("id",         sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("library_id", sa.Integer(), sa.ForeignKey("libraries.id"), nullable=True),
            sa.Column("book_id",    sa.Integer(), sa.ForeignKey("books.id"),     nullable=False),
            sa.Column("user_id",    sa.Integer(), sa.ForeignKey("users.id"),     nullable=False),
            sa.Column("rating",     sa.Integer(), nullable=False),
            sa.Column("review",     sa.Text(),    nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
        if not _index_exists("ix_book_ratings_id", "book_ratings"):
            op.create_index("ix_book_ratings_id",         "book_ratings", ["id"])
        if not _index_exists("ix_book_ratings_library_id", "book_ratings"):
            op.create_index("ix_book_ratings_library_id", "book_ratings", ["library_id"])
        print("✓ Kreirana tablica 'book_ratings'")
    else:
        if not _column_exists("book_ratings", "library_id"):
            op.add_column("book_ratings", sa.Column("library_id", sa.Integer(),
                sa.ForeignKey("libraries.id"), nullable=True))
            if not _index_exists("ix_book_ratings_library_id", "book_ratings"):
                op.create_index("ix_book_ratings_library_id", "book_ratings", ["library_id"])

    # ── 10. mid_reset_count u licenses ───────────────────────────────────────
    if _table_exists("licenses") and not _column_exists("licenses", "mid_reset_count"):
        op.add_column("licenses", sa.Column(
            "mid_reset_count", sa.Integer(), nullable=True, server_default="0"
        ))

    print("✓ 005_fresh_db_fix završen")


def downgrade() -> None:
    pass  # Ova migracija je samo dodavanje — downgrade nije kritičan
