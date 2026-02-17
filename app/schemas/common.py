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

# ============================================================
# 공통 에러 스키마
# ============================================================


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


# ============================================================
# 공통 요청 스키마
# ============================================================


class SurveyAnswer(BaseModel):
    """
    설문 문항 1개에 대한 사용자 응답
    - 문항 텍스트는 그대로 전달
    """

    questionContent: str = Field(..., description="설문 문항 내용")
    selectedOptionSortOrder: int = Field(
        ..., ge=1, description="선택한 응답의 정렬 순서 (강도/빈도 등)"
    )


class UserSurvey(BaseModel):
    """
    사용자 설문 입력
    """

    routineCount: int = Field(..., ge=0, description="사용자가 원하는 루틴 개수")
    survey: List[SurveyAnswer] = Field(..., description="설문 응답 리스트")


# ============================================================
# 공통 응답 스키마
# ============================================================


class TaskStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RecommendationSummary(BaseModel):
    """
    추천 결과 요약 정보
    """

    totalRoutines: int = Field(..., ge=0, description="추천된 루틴 개수")
    totalExercises: int = Field(..., ge=0, description="전체 운동 개수")
