# 공통 스키마 (Common Error 등)

from datetime import datetime
from enum import Enum
from typing import Dict

from pydantic import BaseModel, Field


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ServiceStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    TIMEOUT = "timeout"


class HealthResponse(BaseModel):
    """
    Health check 응답 스키마
    - v1~v3 공통 사용
    """

    status: HealthStatus = Field(..., description="전체 서비스 상태")
    version: str = Field(..., description="API 버전")
    timestamp: datetime = Field(..., description="응답 시각 (UTC)")
    services: Dict[str, ServiceStatus] = Field(..., description="개별 서비스 상태")
