"""Alembic environment configuration for RAKSHAK.

Reads the DATABASE_URL from the application Settings and uses the
declarative Base metadata for autogenerate support.
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Ensure the backend directory is on sys.path so app.* imports resolve.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.db import Base

# Import all models so Alembic autogenerate detects their tables.
import app.models  # noqa: F401, E402

# Alembic Config object — provides access to values in alembic.ini.
config = context.config

# Override sqlalchemy.url with the value from application settings.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Set up Python logging from the config file.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for autogenerate — import all models so Alembic sees them.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in offline mode.

    Emits SQL to stdout without requiring a live database connection.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode.

    Connects to the database and applies migrations directly.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
