"""Alembic environment. Migrations run programmatically from wamt.db.migrate(); the caller
passes an open connection in config.attributes so the same engine/transaction is reused."""

from alembic import context

from wamt.db import Base

config = context.config
target_metadata = Base.metadata


def run() -> None:
    connection = config.attributes.get("connection")
    if connection is None:
        from wamt.db import engine

        with engine().connect() as conn:
            _run(conn)
            conn.commit()
    else:
        _run(connection)


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",  # SQLite can't ALTER most things
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


run()
