# app/services/response/v2.py

"""
V2 응답 빌더
- CoreResponseBuilder를 상속하여 V2 응답 래핑 담당
- TaskResult 직접 생성 (v1_response → TaskResult 재변환 제거)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.domain.routine import Routine, RoutineList
from app.schemas.common import RecommendationSummary, TaskStatus, UserSurvey
from app.schemas.task import (
    PROGRESS_STEP_PERCENTAGE,
    ProgressStep,
    TaskResult,
)
from app.services.response.base import CoreResponseBuilder

logger = logging.getLogger(__name__)


class V2ResponseBuilder(CoreResponseBuilder):
    """
    V2 비동기 응답 빌더

    CoreResponseBuilder.build_core()로 검증된 루틴을
    TaskResult로 래핑하여 반환.
    """

    def build(
        self, output: RoutineList, task_id: str, survey: UserSurvey, *, user_id: int
    ) -> TaskResult:
        """
        RoutineList를 검증하고 TaskResult로 변환.

        Args:
        - output: LLM 또는 rule-based 추천 결과
        - task_id: 작업 ID
        - survey: 사용자 설문 데이터
        - user_id: 사용자 식별자

        Returns:
        - TaskResult: 폴링/콜백 공용 응답 객체

        Raise:
        - RoutineValidationError: 검증 실패 및 fallback도 실패 시
        """
        validated_routines = self.build_core(output, survey)
        return self._create_response(validated_routines, task_id, user_id)

    def build_failed(self, task_id: str, error_message: str, *, user_id: int) -> TaskResult:
        """실패 응답 생성"""
        return TaskResult(
            taskId=task_id,
            userId=user_id,
            status=TaskStatus.FAILED,
            progress=PROGRESS_STEP_PERCENTAGE[ProgressStep.FAILED],
            currentStep=ProgressStep.FAILED.value,
            summary=None,
            errorMessage=error_message,
            completedAt=datetime.now(UTC),
            routines=None,
        )

    def _create_response(
        self, validated_routines: list[Routine], task_id: str, user_id: int
    ) -> TaskResult:
        """검증 완료된 루틴으로 V2 TaskResult 객체 생성"""
        total_exercises = sum(len(r.steps) for r in validated_routines)

        return TaskResult(
            taskId=task_id,
            userId=user_id,
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
