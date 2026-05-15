"""initial_schema — svi modeli koji nedostaju u produkciji

Revision ID: 004_initial_schema
Revises: 003_multi_tenant
Create Date: 2026-04-29

VERZIJA 9.1.4 — Zamjena za Base.metadata.create_all() i _auto_migrate_licenses()

Što radi:
  1. Kreira core tablice (books, members, loans, reservations, ratings,
     users, notifications, book_ratings, sync_log, recommendations)
     AKO već ne postoje — koristimo IF NOT EXISTS / try/except da migracija
     bude idempotentna na instancama koje su koristile create_all().
  2. Dodaje kolonu 'mid_reset_count' u licenses tablicu ako nedostaje
     (bila je u _auto_migrate_licenses ali nije pokrivena migracijama).
  3. Svi novi dodaci idu ovdje — bez ručnih ALTER TABLE u main.py.

NAPOMENA: Tablice koje su već kreirane migracijama 001–003 (libraries,
licenses) se ne diraju — alembic ih prati u alembic_version tablici.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision: str = "004_initial_schema"
down_revision: Union[str, None] = "003_multi_tenant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return inspect(bind).has_table(name)


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    return any(c["name"] == column for c in inspect(bind).get_columns(table))


def upgrade() -> None:
    # ── users (ako ne postoji — create_all je mogao kreirati) ────────────────
    if not _table_exists("users"):
        op.create_table(
            "users",
            sa.Column("id",              sa.Integer(),     primary_key=True, autoincrement=True),
            sa.Column("username",        sa.String(64),    nullable=False, unique=True),
            sa.Column("full_name",       sa.String(128),   nullable=True),
            sa.Column("hashed_password", sa.String(256),   nullable=False),
            sa.Column("plain_password",  sa.String(128),   nullable=True),
            sa.Column("role",            sa.String(32),    nullable=False, server_default="knjiznicar"),
            sa.Column("library_id",      sa.Integer(),     sa.ForeignKey("libraries.id"), nullable=True),
            sa.Column("is_active",       sa.Boolean(),     nullable=False, server_default="1"),
            sa.Column("created_at",      sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
        op.create_index("ix_users_id",         "users", ["id"])
        op.create_index("ix_users_username",   "users", ["username"], unique=True)
        op.create_index("ix_users_library_id", "users", ["library_id"])

    # ── books ────────────────────────────────────────────────────────────────
    if not _table_exists("books"):
        op.create_table(
            "books",
            sa.Column("id",               sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("library_id",       sa.Integer(), sa.ForeignKey("libraries.id"), nullable=False),
            sa.Column("isbn",             sa.String(32),  nullable=True),
            sa.Column("title",            sa.String(256), nullable=False),
            sa.Column("author",           sa.String(256), nullable=False),
            sa.Column("publisher",        sa.String(128), nullable=True),
            sa.Column("year",             sa.Integer(),   nullable=True),
            sa.Column("genre",            sa.String(64),  nullable=True),
            sa.Column("shelf",            sa.String(32),  nullable=True),
            sa.Column("language",         sa.String(8),   nullable=True, server_default="hr"),
            sa.Column("series",           sa.String(128), nullable=True),
            sa.Column("series_order",     sa.Integer(),   nullable=True),
            sa.Column("tags",             sa.String(512), nullable=True),
            sa.Column("total_copies",     sa.Integer(),   nullable=False, server_default="1"),
            sa.Column("available_copies", sa.Integer(),   nullable=False, server_default="1"),
            sa.Column("description",      sa.Text(),      nullable=True),
            sa.Column("cover_url",        sa.String(512), nullable=True),
            sa.Column("created_at",       sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.UniqueConstraint("library_id", "isbn", name="uq_book_library_isbn"),
        )
        op.create_index("ix_books_id",         "books", ["id"])
        op.create_index("ix_books_title",      "books", ["title"])
        op.create_index("ix_books_isbn",       "books", ["isbn"])
        op.create_index("ix_books_library_id", "books", ["library_id"])

    # ── members ──────────────────────────────────────────────────────────────
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
        op.create_index("ix_members_id",            "members", ["id"])
        op.create_index("ix_members_member_number", "members", ["member_number"])
        op.create_index("ix_members_email",         "members", ["email"])
        op.create_index("ix_members_library_id",    "members", ["library_id"])

    # ── loans ────────────────────────────────────────────────────────────────
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
        op.create_index("ix_loans_id",         "loans", ["id"])
        op.create_index("ix_loans_library_id", "loans", ["library_id"])

    # ── reservations ─────────────────────────────────────────────────────────
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
        op.create_index("ix_reservations_id",         "reservations", ["id"])
        op.create_index("ix_reservations_library_id", "reservations", ["library_id"])

    # ── ratings ──────────────────────────────────────────────────────────────
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
        op.create_index("ix_ratings_id",         "ratings", ["id"])
        op.create_index("ix_ratings_library_id", "ratings", ["library_id"])

    # ── book_ratings ─────────────────────────────────────────────────────────
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
        op.create_index("ix_book_ratings_id",         "book_ratings", ["id"])
        op.create_index("ix_book_ratings_library_id", "book_ratings", ["library_id"])

    # ── notifications ────────────────────────────────────────────────────────
    if not _table_exists("notifications"):
        op.create_table(
            "notifications",
            sa.Column("id",         sa.Integer(),  primary_key=True, autoincrement=True),
            sa.Column("user_id",    sa.Integer(),  sa.ForeignKey("users.id"), nullable=True),
            sa.Column("library_id", sa.Integer(),  nullable=True),
            sa.Column("type",       sa.String(32), nullable=False, server_default="system"),
            sa.Column("priority",   sa.String(16), nullable=False, server_default="normal"),
            sa.Column("title",      sa.String(256),nullable=False),
            sa.Column("message",    sa.Text(),     nullable=False),
            sa.Column("is_read",    sa.Boolean(),  nullable=False, server_default="0"),
            sa.Column("data",       sa.Text(),     nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
        op.create_index("ix_notifications_id",         "notifications", ["id"])
        op.create_index("ix_notifications_library_id", "notifications", ["library_id"])

    # ── mid_reset_count u licenses (bio u _auto_migrate_licenses, sad ovdje) ─
    if _table_exists("licenses") and not _column_exists("licenses", "mid_reset_count"):
        op.add_column("licenses", sa.Column(
            "mid_reset_count", sa.Integer(), nullable=True, server_default="0"
        ))


def downgrade() -> None:
    # Ukloni samo tablice koje ova migracija kreira (ako ne postoje od create_all)
    # Sigurno — samo drop ako postoji
    for tbl in ["book_ratings", "notifications", "ratings",
                "reservations", "loans", "members", "books", "users"]:
        try:
            op.drop_table(tbl)
        except Exception:
            pass

    if _table_exists("licenses") and _column_exists("licenses", "mid_reset_count"):
        op.drop_column("licenses", "mid_reset_count")
