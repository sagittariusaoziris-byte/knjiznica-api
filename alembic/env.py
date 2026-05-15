"""
alembic/env.py — Knjižnica v9.1.4
Konfiguracija Alembic migracija.
"""
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Uvezi SVE modele da Alembic vidi sve tablice (autogenerate)
from app.database import Base
from app.models import models               # noqa: Book, Member, Loan, Reservation, Rating
from app.models.library import Library      # noqa
from app.models.license_record import LicenseRecord  # noqa
from app.models.notification import Notification     # noqa
from app.models.user import User            # noqa
from app.models.book_rating import BookRating        # noqa
from app.models.recommendations import BookRecommendation, MemberBookmark, ReservationRequest  # noqa

config = context.config

# Čitaj DATABASE_URL iz env varijable (Render, lokalni .env...)
database_url = os.environ.get("DATABASE_URL", "")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Uključi compare_type za detekciju promjena tipa kolona
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
