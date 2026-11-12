from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.schemas import DatabaseHealth, HealthResponse
from app.services.health_service import check_database


router = APIRouter(
    prefix="/health",
    tags=["Health"]
)


@router.get("", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        app=settings.APP_NAME,
        version=settings.APP_VERSION
    )


@router.get(
    "/db",
    response_model=DatabaseHealth,
    responses={503: {"model": DatabaseHealth}}
)
def database_health(db: Session = Depends(get_db)):
    result = check_database(db)

    if result.status != "ok":
        return JSONResponse(
            status_code=503,
            content=result.model_dump()
        )

    return result
