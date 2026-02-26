from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv
import os

from sqlalchemy import engine_from_config, pool
from alembic import context

# Load .env from project root so DATABASE_URL / DATABASE_PATH are available
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

config = context.config

# Determine database URL: prefer DATABASE_URL (Postgres), fall back to SQLite
database_url = os.getenv("DATABASE_URL", "")
if database_url.startswith("postgresql://"):
    config.set_main_option("sqlalchemy.url", database_url)
else:
    db_path = os.getenv("DATABASE_PATH", "intake_eval.db")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _is_sqlite() -> bool:
    url = config.get_main_option("sqlalchemy.url")
    return url.startswith("sqlite")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_is_sqlite(),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_is_sqlite(),
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
