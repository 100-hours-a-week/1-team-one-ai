# app/schemas/v2/response.py
"""
V2 응답 데이터 스키마
- class TaskStatus(str, Enum)
- class ProgressStep(str, Enum)
- class TaskAcceptedResponse(BaseModel)   — POST 202 즉시 응답
- class TaskResult(BaseModel)             — GET 폴링 응답
- class TaskResult(BaseModel)        — coreBE 콜백 페이로드
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ExerciseType, Side  # noqa: F401
from app.schemas.v1.response import (  # noqa: F401
    LLMRoutineOutput,
    RecommendationSummary,
    Routine,
    RoutineStep,
)


class TaskStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProgressStep(str, Enum):
    """
    진행 단계별 메시지 (v1: LLM 추론 단계부터 시작)
    - v2 이상에서는 HEALTH_SCORE, CATEGORY_PRIORITY, EXERCISE_SEARCH 추가
    """

    # v2+ 전용
    HEALTH_SCORE = "건강 점수 계산 중"  # 10%
    CATEGORY_PRIORITY = "카테고리 우선순위 분석 중"  # 25%
    EXERCISE_SEARCH = "맞춤 운동 검색 중"  # 40%

    # v1~
    LLM_INFERENCE = "AI가 최적의 루틴 구성 중"  # 60%
    RESULT_VALIDATION = "최종 추천 결과 검증 중"  # 75%
    COMPLETED = "운동 플랜 추천 완료!"  # 100%

    FAILED = "추천 실패"  # 0%


PROGRESS_STEP_PERCENTAGE: dict[ProgressStep, int] = {
    ProgressStep.FAILED: 0,
    ProgressStep.HEALTH_SCORE: 10,
    ProgressStep.CATEGORY_PRIORITY: 25,
    ProgressStep.EXERCISE_SEARCH: 40,
    ProgressStep.LLM_INFERENCE: 60,
    ProgressStep.RESULT_VALIDATION: 75,
    ProgressStep.COMPLETED: 100,
}


# ============================================================
# V2 전용 응답 모델
# ============================================================


class TaskAcceptedResponse(BaseModel):
    """
    POST /api/v2/routines 즉시 응답 (HTTP 202)
    - taskId와 초기 상태만 반환
    """

    model_config = ConfigDict(extra="forbid")

    taskId: str = Field(..., description="추천 태스크 ID")
    status: TaskStatus = Field(default=TaskStatus.IN_PROGRESS, description="태스크 상태")
    progress: int = Field(default=0, ge=0, le=100, description="진행률 (0~100)")
    currentStep: str = Field(default="추천 요청 접수됨", description="현재 처리 단계 설명")


class TaskResult(BaseModel):
    """
    Task 상태 단일 모델
    - polling / callback 공용
    - 태스크 상태 + 완료 시 결과 포함
    - 성공/진행/실패 모두 동일한 구조로 전송

    1. polling: GET /api/v2/routines/{taskId} 폴링 응답
    2. callback: coreBE에 전송할 콜백 페이로드

    """

    model_config = ConfigDict(extra="forbid")

    taskId: str = Field(..., description="추천 태스크 ID")
    status: TaskStatus = Field(..., description="태스크 상태")

    progress: int = Field(..., ge=0, le=100, description="진행률 (0~100)")
    currentStep: str = Field(..., description="현재 처리 단계 설명")

    summary: Optional[RecommendationSummary] = Field(
        None, description="추천 결과 요약 (완료 시 제공)"
    )
    routines: Optional[List[Routine]] = Field(None, description="추천된 루틴 목록 (완료 시 제공)")
    errorMessage: Optional[str] = Field(None, description="실패 시 에러 메시지")
    completedAt: Optional[datetime] = Field(None, description="태스크 완료 시각 (UTC)")
