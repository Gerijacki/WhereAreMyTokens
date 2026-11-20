"""The Alembic revisions must produce exactly the schema the models describe (CLAUDE.md: schema changes need a revision)."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from wamt.db import Base, migrate


def test_migrations_match_the_models(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'drift.db'}")
    migrate(eng)
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"Models changed without an Alembic revision: {diff}"
