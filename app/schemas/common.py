# app/schemas/common.py
"""
공통 스키마 (Common Error 등)
- class ErrorDetail(BaseModel)
- class ErrorResponse(BaseModel)
- class HealthStatus(str, Enum)
- class HealthResponse(BaseModel)
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    field: Optional[str] = None
    reason: str


class ErrorResponse(BaseModel):
    code: str
    errors: List[ErrorDetail]


class HealthStatus(str, Enum):
    """시스템/서비스 상태"""

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
    services: Dict[str, HealthStatus] = Field(..., description="개별 서비스 상태")


class ExerciseType(str, Enum):
    """운동 수행 방식 - 전체 시스템에서 공유되는 Core Enum"""

    REPS = "REPS"
    DURATION = "DURATION"
