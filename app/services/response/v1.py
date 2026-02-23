# app/services/response/v1.py

"""
V1 응답 빌더
- CoreResponseBuilder를 상속하여 V1 응답 래핑 담당
- RecommendationResponseV1 생성
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.domain.routine import Routine, RoutineList
from app.schemas.common import RecommendationSummary, TaskStatus, UserSurvey
from app.schemas.v1.response import (
    PROGRESS_STEP_PERCENTAGE,
    ProgressStep,
    RecommendationResponseV1,
)
from app.services.response.base import CoreResponseBuilder

logger = logging.getLogger(__name__)


class V1ResponseBuilder(CoreResponseBuilder):
    """
    V1 동기 응답 빌더

    CoreResponseBuilder.build_core()로 검증된 루틴을
    RecommendationResponseV1로 래핑하여 반환.
    """

    def build(
        self, output: RoutineList, task_id: str, survey: UserSurvey
    ) -> RecommendationResponseV1:
        """
        RoutineList를 검증하고 RecommendationResponseV1로 변환.

        Args:
        - output: LLM 또는 rule-based 추천 결과
        - task_id: 작업 ID
        - survey: 사용자 설문 데이터

        Returns:
        - RecommendationResponseV1: API 응답 객체

        Raise:
        - RoutineValidationError: 검증 실패 및 fallback도 실패 시
        """
        validated_routines = self.build_core(output, survey)
        return self._create_response(validated_routines, task_id)

    def build_failed(self, task_id: str, error_message: str) -> RecommendationResponseV1:
        """실패 응답 생성"""
        return RecommendationResponseV1(
            taskId=task_id,
            status=TaskStatus.FAILED,
            progress=0,
            currentStep="추천 실패",
            summary=None,
            errorMessage=error_message,
            completedAt=datetime.now(UTC),
            routines=None,
        )

    def _create_response(
        self, validated_routines: list[Routine], task_id: str
    ) -> RecommendationResponseV1:
        """검증 완료된 루틴으로 V1 응답 객체 생성"""
        total_exercises = sum(len(r.steps) for r in validated_routines)

        return RecommendationResponseV1(
            taskId=task_id,
            status=TaskStatus.COMPLETED,
            progress=PROGRESS_STEP_PERCENTAGE[ProgressStep.COMPLETED],
            currentStep=ProgressStep.COMPLETED.value,
            summary=RecommendationSummary(
                totalRoutines=len(validated_routines),
                totalExercises=total_exercises,
            ),
            errorMessage=None,
            completedAt=datetime.now(UTC),
            routines=validated_routines,
        )
