# app/api/v1/health.py
from datetime import datetime, timezone

from fastapi import APIRouter

from app.schemas.common import HealthResponse, HealthStatus, ServiceStatus

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status=HealthStatus.HEALTHY,
        version="v0.1.0",
        timestamp=datetime.now(timezone.utc),
        services={"api": ServiceStatus.HEALTHY},
    )
