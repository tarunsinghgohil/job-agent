"""Alembic environment.

The database URL comes from application settings, never from alembic.ini, so
there is exactly one place a connection string is configured.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.db.models import Base  # imports every model, populating metadata

config = context.config
config.set_main_option("sqlalchemy.url", settings.resolved_database_url())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object_, name, type_, reflected, compare_to) -> bool:
    """Skip the pgvector extension's own internal tables, if any appear."""
    if type_ == "table" and name.startswith("pg_"):
        return False
    return True


def render_item(type_, obj, autogen_context) -> bool:
    """Ensure custom column types carry their import into the migration.

    Autogenerate renders ``app.db.base.JSONColumn()`` but does not add the
    import for it, which makes the generated file fail at runtime.
    """
    if type_ == "type" and obj.__class__.__module__.startswith("app.db.base"):
        autogen_context.imports.add("import app.db.base")
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
        render_item=render_item,
        # SQLite cannot ALTER most columns; batch mode rewrites the table.
        render_as_batch=settings.is_sqlite,
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
            include_object=include_object,
            render_item=render_item,
            render_as_batch=settings.is_sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
