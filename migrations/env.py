"""Alembic environment configuration.

This module is executed by Alembic for every migration command (``upgrade``,
``downgrade``, ``revision --autogenerate``, etc.).  It:

1. Reads ``DATABASE_URL`` from the environment so credentials never live in
   ``alembic.ini``.
2. Imports all SQLAlchemy models via ``app.models`` so that
   ``--autogenerate`` can diff the current schema against the metadata.
3. Supports both **offline** mode (generates SQL without a live connection)
   and **online** mode (applies migrations against a running database).
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# Alembic Config object — provides access to values in alembic.ini.
# ---------------------------------------------------------------------------

config = context.config

# Interpret the config file for Python logging if it contains a logging
# section.  This line sets up loggers as defined in alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Override sqlalchemy.url from the environment variable so that credentials
# are never hard-coded in alembic.ini.
# ---------------------------------------------------------------------------

database_url = os.environ.get(
    "DATABASE_URL",
    "postgresql://rbac_user:rbac_password@localhost:5432/rbac_auditor",
)
# asyncpg scheme is not supported by Alembic's synchronous engine; normalise.
database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
config.set_main_option("sqlalchemy.url", database_url)

# ---------------------------------------------------------------------------
# Import models so Alembic's autogenerate can inspect their metadata.
#
# At this stage of the project the models package is a stub; importing it
# is safe and will grow as models are added in later tasks.
# ---------------------------------------------------------------------------

try:
    from app.models import Base

    target_metadata = Base.metadata
except ImportError:
    # Models not yet implemented — autogenerate will produce an empty
    # migration.  This is expected during the infrastructure bootstrap phase.
    target_metadata = None


# ---------------------------------------------------------------------------
# Offline migration mode
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Emit migration SQL to stdout without requiring a live DB connection.

    This is useful for reviewing what Alembic *would* execute, or for
    generating SQL scripts to hand off to a DBA.
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


# ---------------------------------------------------------------------------
# Online migration mode
# ---------------------------------------------------------------------------


def run_migrations_online() -> None:
    """Apply migrations against a live database connection."""
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


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
