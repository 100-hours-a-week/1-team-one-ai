from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TaskStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProgressStep(str, Enum):
    """
    진행 단계별 메시지 (v1: LLM 추론 단계부터 시작)
    - v2 이상에서는 HEALTH_SCORE, CATEGORY_PRIORITY, EXERCISE_SEARCH 추가 예정
    """

    # v2+ 전용 (현재 미사용)
    # HEALTH_SCORE = "건강 점수 계산 중"            # 10%
    # CATEGORY_PRIORITY = "카테고리 우선순위 분석 중"  # 25%
    # EXERCISE_SEARCH = "맞춤 운동 검색 중"          # 40%

    # v1 사용
    LLM_INFERENCE = "AI가 최적의 루틴 구성 중"  # 60%
    RESULT_VALIDATION = "최종 추천 결과 검증 중"  # 75%
    COMPLETED = "운동 플랜 추천 완료!"  # 100%


# 진행 단계별 progress 값 매핑
PROGRESS_STEP_PERCENTAGE: dict[ProgressStep, int] = {
    # v2+ 전용 (현재 미사용)
    # ProgressStep.HEALTH_SCORE = 10,
    # ProgressStep.CATEGORY_PRIORITY = 25,
    # ProgressStep.EXERCISE_SEARCH = 40,
    # v1~v3
    ProgressStep.LLM_INFERENCE: 60,
    ProgressStep.RESULT_VALIDATION: 75,
    ProgressStep.COMPLETED: 100,
}


class ExerciseType(str, Enum):
    REPS = "REPS"
    DURATION = "DURATION"


class RoutineStep(BaseModel):
    """
    루틴 내 단일 운동 스텝
    """

    exerciseId: str = Field(..., description="운동 ID")
    type: ExerciseType = Field(..., description="운동 수행 방식")
    stepOrder: int = Field(..., ge=1, description="루틴 내 순서")

    limitTime: int = Field(..., ge=0, description="해당 스텝 제한 시간(초)")
    durationTime: Optional[int] = Field(
        None, ge=0, description="지속 시간 기반 운동일 경우 수행 시간(초)"
    )
    targetReps: Optional[int] = Field(
        None, ge=0, description="횟수 기반 운동일 경우 목표 반복 횟수"
    )


class Routine(BaseModel):
    """
    추천된 루틴 1개
    """

    routineOrder: int = Field(..., ge=1, description="루틴 순서")
    reason: str = Field(..., description="루틴 구성 이유")

    steps: List[RoutineStep] = Field(..., description="루틴에 포함된 운동 스텝 목록")


class RecommendationSummary(BaseModel):
    """
    추천 결과 요약 정보
    - v1 기준으로는 단순 카운트 정보만 제공
    """

    totalRoutines: int = Field(..., ge=0, description="추천된 루틴 개수")
    totalExercises: int = Field(..., ge=0, description="전체 운동 개수")


class RecommendationResponseV1(BaseModel):
    """
    v1 추천 API 응답
    - 태스크 상태 기반 비동기 처리 결과
    """

    model_config = ConfigDict(extra="forbid")

    taskId: str = Field(..., description="추천 태스크 ID")
    status: TaskStatus = Field(..., description="태스크 상태")
    progress: int = Field(..., ge=0, le=100, description="진행률 (0~100)")
    currentStep: str = Field(..., description="현재 처리 단계 설명")

    summary: Optional[RecommendationSummary] = Field(
        None, description="추천 결과 요약 (완료 시 제공)"
    )
    errorMessage: Optional[str] = Field(None, description="실패 시 에러 메시지")
    completedAt: Optional[datetime] = Field(None, description="태스크 완료 시각 (UTC)")

    routines: Optional[List[Routine]] = Field(None, description="추천된 루틴 목록 (완료 시 제공)")
