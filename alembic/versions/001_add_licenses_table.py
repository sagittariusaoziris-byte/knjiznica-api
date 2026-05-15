"""add_licenses_table

Revision ID: 001_licenses
Revises:
Create Date: 2026-04-17

PATCH 1 v8.5.6 — Kreira tablicu 'licenses' za praćenje licencnih ključeva.
Bez ove migracije svi /admin/license/* endpointi bacaju OperationalError
na produkcijskim instalacijama gdje Base.metadata.create_all() nije pozvan.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001_licenses"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "licenses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("license_key", sa.Text(), nullable=False),
        sa.Column("issued", sa.DateTime(), nullable=False),
        sa.Column("expiry", sa.DateTime(), nullable=False),
        sa.Column("machine_id", sa.String(length=128), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("license_key", name="uq_licenses_license_key"),
    )
    op.create_index("ix_licenses_id", "licenses", ["id"], unique=False)
    op.create_index("ix_licenses_email", "licenses", ["email"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_licenses_email", table_name="licenses")
    op.drop_index("ix_licenses_id", table_name="licenses")
    op.drop_table("licenses")
