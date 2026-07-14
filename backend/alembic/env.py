import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Repo layout: alembic/env.py sits at backend/alembic/, app/ is a sibling of
# alembic/ — add backend/ to sys.path so `import app...` resolves the same
# way it does for the running FastAPI process.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# app/db/base.py is the existing import hub every domain's models.py
# registers with — importing it here is what makes Base.metadata (and thus
# autogenerate) see every table, matching what Base.metadata.create_all()
# already relies on in app/main.py's lifespan.
from app.db.base import Base  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.database import to_sync_url  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Drive the connection URL from the app's own settings (DATABASE_URL) rather
# than alembic.ini's static sqlalchemy.url — one source of truth, and this
# is how migrations pick up Supabase/Postgres once DATABASE_URL points
# there. Alembic's sync engine needs a sync driver — reuses
# core/database.py's to_sync_url rather than duplicating that scheme
# normalization here.
#
# set_main_option() stores the value in a ConfigParser section, which
# treats "%" as its interpolation escape character — a URL-encoded
# password (e.g. "%40" for "@", exactly what Supabase's dashboard-issued
# passwords produce) would otherwise raise "invalid interpolation syntax"
# before a single migration runs. Doubling "%" to "%%" is ConfigParser's
# own documented escape, not a general URL-encoding concern.
config.set_main_option("sqlalchemy.url", to_sync_url(get_settings().DATABASE_URL).replace("%", "%%"))


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

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
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
