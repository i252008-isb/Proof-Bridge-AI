import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import SessionLocal, engine, init_db
from app.errors import register_exception_handlers
from app.routers import (
    agreements,
    analysis,
    auth,
    case_history,
    evidence,
    health,
    human_reviews,
    payment,
    paypal,
    projects,
    reports,
    requirements
)
from app.services.health_service import check_database


logger = logging.getLogger("proofbridge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    if len(settings.SECRET_KEY) < 32:
        logger.warning(
            "SECRET_KEY is shorter than 32 characters. Use a long random "
            "value outside local development."
        )

    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)

    try:
        init_db()

        with SessionLocal() as db:
            result = check_database(db)

        if result.status == "ok":
            logger.info("Database ready (%.1f ms).", result.latency_ms)
        else:
            logger.warning(
                "Database not ready: %s (missing tables: %s).",
                result.database,
                result.missing_tables or "none"
            )
    except Exception:
        logger.exception("Database startup check failed; starting degraded.")

    yield

    logger.info("Shutting down %s.", settings.APP_NAME)
    engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    description="Evidence intelligence and investigation platform",
    version=settings.APP_VERSION,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"]
)

register_exception_handlers(app)

app.include_router(auth.router)
app.include_router(health.router)
app.include_router(projects.router)
app.include_router(requirements.router)
app.include_router(agreements.router)
app.include_router(evidence.router)
app.include_router(analysis.router)
app.include_router(reports.router)
app.include_router(human_reviews.pending_router)
app.include_router(human_reviews.router)
app.include_router(case_history.router)
app.include_router(paypal.router)
app.include_router(payment.router)


@app.get("/", tags=["Root"])
def home():
    return {"message": "Welcome to ProofBridge AI"}
