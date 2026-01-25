# app/api/v1/health.py
"""
헬스 체크 API (v1)
- @router.get("/health", response_model=HealthResponse)

Raise: None

HTTP Status:
- 200: OK
- 503: Service Unavailable
"""

from datetime import datetime, timezone

from fastapi import APIRouter

from app.data.loader import exercise_repository
from app.schemas.common import HealthResponse, HealthStatus

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    exercises_status = (
        HealthStatus.HEALTHY if exercise_repository.is_valid() else HealthStatus.UNHEALTHY
    )

    # 전체 상태: 하나라도 unhealthy면 degraded
    overall_status = (
        HealthStatus.HEALTHY if exercises_status == HealthStatus.HEALTHY else HealthStatus.DEGRADED
    )

    return HealthResponse(
        status=overall_status,
        version="v0.1.0",
        timestamp=datetime.now(timezone.utc),
        services={
            "api": HealthStatus.HEALTHY,
            "exercises": exercises_status,
        },
    )
