from collections.abc import Generator
import logging
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.schema import CreateColumn

from app.config import BASE_DIR, settings


logger = logging.getLogger("proofbridge.database")


def resolve_database_url(database_url: str) -> URL:
    """Make relative SQLite paths independent of the launch directory."""
    url = make_url(database_url)

    if url.get_backend_name() != "sqlite":
        return url

    database = url.database

    if not database or database == ":memory:":
        return url

    path = Path(database)

    if path.is_absolute():
        return url

    return url.set(database=str((BASE_DIR / path).resolve()))


database_url = resolve_database_url(settings.DATABASE_URL)

connect_args = {}

if database_url.get_backend_name() == "sqlite":
    connect_args = {"check_same_thread": False}


engine = create_engine(
    database_url,
    connect_args=connect_args,
    pool_pre_ping=True
)


@event.listens_for(engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    if database_url.get_backend_name() != "sqlite":
        return

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


class Base(DeclarativeBase):
    pass


def _add_missing_analysis_result_columns() -> None:
    """Add nullable analysis columns without touching existing rows.

    ``create_all`` only creates missing tables, so an existing deployment
    needs an additive ALTER for the columns introduced by the evidence
    analysis pipeline. Every new column is nullable, which keeps all
    historical rows valid.
    """
    import app.models as models

    inspector = inspect(engine)

    if "analysis_results" not in inspector.get_table_names():
        return

    existing = {
        column["name"]
        for column in inspector.get_columns("analysis_results")
    }
    new_columns = [
        column
        for column in models.AnalysisResult.__table__.columns
        if column.name not in existing
    ]

    if not new_columns:
        return

    existing_indexes = {
        index["name"]
        for index in inspect(engine).get_indexes("analysis_results")
    }

    with engine.begin() as connection:
        for column in new_columns:
            ddl = str(
                CreateColumn(column).compile(dialect=engine.dialect)
            )
            connection.execute(
                text(
                    f"ALTER TABLE analysis_results ADD COLUMN {ddl}"
                )
            )
            logger.info(
                "Added analysis_results.%s without changing existing rows.",
                column.name,
            )

        if "ix_analysis_results_report_id" not in existing_indexes:
            connection.execute(
                text(
                    "CREATE INDEX ix_analysis_results_report_id "
                    "ON analysis_results (report_id)"
                )
            )


def _add_missing_project_columns() -> None:
    """Add missing project columns (amount, currency, paypal_order_id) without touching existing rows."""
    import app.models as models

    inspector = inspect(engine)

    if "projects" not in inspector.get_table_names():
        return

    existing = {
        column["name"]
        for column in inspector.get_columns("projects")
    }
    new_columns = [
        column
        for column in models.Project.__table__.columns
        if column.name not in existing
    ]

    if not new_columns:
        return

    with engine.begin() as connection:
        for column in new_columns:
            ddl = str(
                CreateColumn(column).compile(dialect=engine.dialect)
            )
            connection.execute(
                text(
                    f"ALTER TABLE projects ADD COLUMN {ddl}"
                )
            )
            logger.info(
                "Added projects.%s without changing existing rows.",
                column.name,
            )


def init_db() -> None:
    """Create missing tables and add nullable columns only."""
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _add_missing_analysis_result_columns()
    _add_missing_project_columns()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()

    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
