from alembic import context
from sqlalchemy import create_engine, pool

from app.config import get_db_path
from app.db import database_url
from app.models import Base

config = context.config
target_metadata = Base.metadata


def get_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return database_url(db_path)


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
