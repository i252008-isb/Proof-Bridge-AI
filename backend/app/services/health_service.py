import logging
from time import perf_counter

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.schemas import DatabaseHealth


logger = logging.getLogger("proofbridge.health")

EXPECTED_TABLES = frozenset({
    "users",
    "projects",
    "requirements",
    "evidence",
    "analysis_results",
    "case_status_log",
    "reports",
    "human_reviews",
    "paypal_transactions",
})


def check_database(db: Session) -> DatabaseHealth:
    started = perf_counter()

    try:
        db.execute(text("SELECT 1"))
        present_tables = set(inspect(db.get_bind()).get_table_names())
    except SQLAlchemyError:
        logger.warning("Database health check failed.", exc_info=True)
        return DatabaseHealth(
            status="degraded",
            database="unavailable",
            latency_ms=_elapsed_ms(started)
        )

    latency_ms = _elapsed_ms(started)
    missing_tables = sorted(EXPECTED_TABLES - present_tables)

    if missing_tables:
        logger.warning("Database is missing tables: %s", missing_tables)
        return DatabaseHealth(
            status="degraded",
            database="ok",
            latency_ms=latency_ms,
            missing_tables=missing_tables
        )

    return DatabaseHealth(
        status="ok",
        database="ok",
        latency_ms=latency_ms
    )


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 2)
