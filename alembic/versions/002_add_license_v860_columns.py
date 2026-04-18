"""add_license_v860_columns

Revision ID: 002_license_v860
Revises: 001_licenses
Create Date: 2026-04-18

Dodaje kolone koje nedostaju u tablici 'licenses' (v8.6.0 nadogradnja).
Migracija je idempotentna — provjerava postoje li kolone prije dodavanja.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "002_license_v860"
down_revision: Union[str, None] = "001_licenses"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    new_columns = [
        ("activated_at",     sa.DateTime(),       True),
        ("last_seen",        sa.DateTime(),       True),
        ("hostname",         sa.String(255),      True),
        ("os_platform",      sa.String(64),       True),
        ("os_version",       sa.String(128),      True),
        ("app_version",      sa.String(32),       True),
        ("activation_count", sa.Integer(),        False),  # server_default below
        ("notes",            sa.Text(),           True),
    ]
    for col_name, col_type, nullable in new_columns:
        if not _column_exists("licenses", col_name):
            kwargs = {"nullable": nullable}
            if col_name == "activation_count":
                kwargs["server_default"] = "0"
            op.add_column("licenses", sa.Column(col_name, col_type, **kwargs))


def downgrade() -> None:
    for col in ["notes", "activation_count", "app_version",
                "os_version", "os_platform", "hostname", "last_seen", "activated_at"]:
        if _column_exists("licenses", col):
            op.drop_column("licenses", col)
