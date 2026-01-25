# app/services/response_builder.py

"""
추천 응답 빌더
- LLMRoutineOutput 유효성 검증
- 유효성 미충족 시 보완 프로세스
- RecommendationResponseV1 생성
"""

from __future__ import annotations  # noqa: I001

import logging
from datetime import UTC, datetime

from app.core.config import RoutineTimePolicy
from app.schemas.v1.request import UserSurvey
from app.core.exceptions import RoutineValidationError
from app.schemas.v1.response import (
    PROGRESS_STEP_PERCENTAGE,
    LLMRoutineOutput,
    ProgressStep,
    RecommendationResponseV1,
    RecommendationSummary,
    Routine,
    RoutineStep,
    TaskStatus,
)
from app.services.rule_based_recommender import RuleBasedRecommender

logger = logging.getLogger(__name__)


class ResponseBuilder:
    """
    LLMRoutineOutput → RecommendationResponseV1 변환

    동작 흐름:
    1. 비즈니스 규칙 기반 유효성 검증
    2. 유효성 미충족 시 보완 프로세스
    3. RecommendationResponseV1 생성
    """

    # 비즈니스 규칙: 루틴 총 시간 (RoutineTimePolicy 참조)
    MIN_ROUTINE_TIME = RoutineTimePolicy.MIN_TIME
    MAX_ROUTINE_TIME = RoutineTimePolicy.MAX_TIME
    TARGET_ROUTINE_TIME = RoutineTimePolicy.TARGET_TIME

    def __init__(
        self,
        valid_exercise_ids: frozenset[str] | None = None,
        fallback_recommender: RuleBasedRecommender | None = None,
    ) -> None:
        """
        Args:
        - valid_exercise_ids: 유효한 exerciseId 집합.
            None이면 exercise_repository.exercise_ids 사용.
        - fallback_recommender: Rule-based fallback 추천기.
            None이면 exercise_repository.raw_data로 새로 생성.

        Note:
        - 테스트 시 명시적으로 주입하여 mock 사용 가능
        - 프로덕션에서는 None으로 호출하여 기본값 사용 권장
        """
        # Lazy import to avoid circular dependency
        from app.data.loader import exercise_repository

        self._valid_exercise_ids = (
            valid_exercise_ids
            if valid_exercise_ids is not None
            else exercise_repository.exercise_ids
        )

        self._fallback_recommender = (
            fallback_recommender
            if fallback_recommender is not None
            else RuleBasedRecommender(exercise_repository.raw_data)
        )

    def build(
        self, output: LLMRoutineOutput, task_id: str, survey: UserSurvey | None = None
    ) -> RecommendationResponseV1:
        """
        LLMRoutineOutput을 검증하고 RecommendationResponseV1로 변환.

        Args:
        - output: LLM 또는 rule-based 추천 결과
        - task_id: 작업 ID

        Returns:
        - RecommendationResponseV1: API 응답 객체

        Raise:
        - RoutineValidationError: _validate_and_fix 실패 시
            - 루틴이 없을 시
            - 유효한 루틴 스텝이 없을 시
        """
        try:
            validated_routines = self._validate_and_fix(output.routines)
            return self._create_response(validated_routines, task_id=task_id)

        except RoutineValidationError as e:  # fallback: Rule-Based
            if survey:
                logger.warning("LLM 루틴 검증 실패, rule-based fallback 시도: %s", e)
                fallback_output = self._fallback_recommender.recommend_routines(survey)

                # Validate fallback output (should always succeed)
                validated_routines = self._validate_and_fix(fallback_output.routines)
                return self._create_response(validated_routines, task_id=task_id)

            # survey가 없으면 fallback 불가, re-raise
            raise

    def build_failed(self, task_id: str, error_message: str) -> RecommendationResponseV1:
        """
        실패 응답 생성

        Args:
        - error_message: 에러 메시지

        Returns:
        - RecommendationResponseV1: 실패 상태 응답

        Raise:
        - None
        """
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

    def _validate_and_fix(self, routines: list[Routine]) -> list[Routine]:
        """
        루틴 유효성 검증 및 보완.

        검증 항목:
        1. 루틴이 비어 있지 않은지
        2. 각 루틴의 스텝 수가 범위 내인지
        3. exerciseId가 유효한지 (valid_exercise_ids 설정 시)
        4. stepOrder가 연속적인지

        보완 항목:
        - stepOrder 재정렬
        - routineOrder 재정렬

        Raise:
        - RoutineValidationError: 루틴 없을 시, 유효한 루틴 스텝이 없을 시
        """
        if not routines:
            raise RoutineValidationError("추천된 루틴이 없습니다.")

        validated: list[Routine] = []

        for idx, routine in enumerate(routines):
            fixed_routine = self._validate_single_routine(routine, idx + 1)
            # 유효한 스텝이 없을 시 RoutineValidationError 발생 가능
            validated.append(fixed_routine)

        logger.info("루틴 검증 완료: %d개 루틴", len(validated))
        return validated

    def _validate_single_routine(self, routine: Routine, expected_order: int) -> Routine:
        """
        단일 루틴 검증 및 보완
        1. 스텝 유효성 검증
        2. exerciseId 유효성 검증
        3. stepOrder 연속성 검증
        4. limitTime 검증

        Raise:
        - RoutineValidationError: _filter_valid_exercises 에서 스텝 다 삭제된 경우
        """
        steps = routine.steps  # list[RoutineStep]
        if not steps:
            raise RoutineValidationError(
                f"루틴 {expected_order}에 스텝이 없습니다.", invalid_routines=[expected_order]
            )

        # exerciseId 유효성 검증
        if self._valid_exercise_ids:
            steps = self._filter_valid_exercises(steps, routine.routineOrder)
            # steps: 유효한 exerciseId를 가진 스텝 목록
            # raise RoutineValidationError if all steps removed

        # stepOrder 재정렬 (1부터 연속)
        fixed_steps = self._reorder_steps(steps)

        # limitTime 총합 검증 및 조정
        fixed_steps = self._validate_total_time(fixed_steps, expected_order)

        # routineOrder 보정
        return Routine(
            routineOrder=expected_order,
            reason=routine.reason,
            steps=fixed_steps,
        )

    def _filter_valid_exercises(
        self, steps: list[RoutineStep], routine_order: int
    ) -> list[RoutineStep]:
        """
        유효하지 않은 exerciseId를 가진 스텝 필터링

        input:
        - steps (list[RoutineStep]): 필터링할 스텝 목록
        - routine_order: 루틴 순서

        output:
        - valid_steps (list[RoutineStep]): 유효한 스텝 목록

        Raise:
        - RoutineValidationError: 유효한 스텝이 하나도 없음
        """
        valid_steps = []

        for step in steps:  # RoutineStep
            if step.exerciseId in self._valid_exercise_ids:  # type: ignore (함수 호출 전에 None 검증함)
                valid_steps.append(step)

            else:
                logger.warning(
                    "루틴 %d: 유효하지 않은 exerciseId 제거: %s",
                    routine_order,
                    step.exerciseId,
                )

        # 스텝이 다 없어진 경우
        if not valid_steps:
            raise RoutineValidationError(
                f"루틴 {routine_order}의 모든 스텝이 유효하지 않은 exerciseId로 제거되었습니다.",
                invalid_routines=[routine_order],
            )

        return valid_steps

    def _reorder_steps(self, steps: list) -> list:
        """
        stepOrder를 1부터 연속으로 재정렬

        Raise:
        - None
        """

        return [
            RoutineStep(
                exerciseId=step.exerciseId,
                type=step.type,
                stepOrder=idx + 1,
                limitTime=step.limitTime,
                durationTime=step.durationTime,
                targetReps=step.targetReps,
            )
            for idx, step in enumerate(steps)
        ]

    def _validate_total_time(
        self, steps: list[RoutineStep], routine_order: int
    ) -> list[RoutineStep]:
        """
        루틴 총 시간 검증 및 조정.

        - 목표 범위: 150 ~ 210초
        - 초과 시: 뒤에서부터 스텝 제거
        - 미달 시: rule-based 스텝 추가로 보충

        Args:
        - steps: 검증할 스텝 목록
        - routine_order: 루틴 순서 (로깅용)

        Returns:
        - 조정된 스텝 목록
        """
        total_time = sum(step.limitTime for step in steps)

        # 범위 내: 그대로 반환
        if self.MIN_ROUTINE_TIME <= total_time <= self.MAX_ROUTINE_TIME:
            logger.debug("루틴 %d: 총 시간 %d초 (범위 내)", routine_order, total_time)
            return steps

        # 시간 초과: 뒤에서부터 스텝 제거
        if total_time > self.MAX_ROUTINE_TIME:
            return self._trim_steps_to_fit(steps, routine_order, total_time)

        # 시간 미달: rule-based 스텝 추가
        return self._fill_time_gap(steps, routine_order, total_time)

    def _fill_time_gap(
        self,
        steps: list[RoutineStep],
        routine_order: int,
        current_time: int,
    ) -> list[RoutineStep]:
        """
        시간 미달 시 rule-based 스텝 추가로 보충.

        Args:
        - steps: 기존 스텝 목록
        - routine_order: 루틴 순서 (로깅용)
        - current_time: 현재 총 시간

        Returns:
        - 보충된 스텝 목록 (stepOrder 재정렬됨)

        Raise:
        - None
        """
        needed_time = self.MIN_ROUTINE_TIME - current_time
        used_ids = {step.exerciseId for step in steps}

        filler_steps = self._fallback_recommender.get_filler_steps(
            target_time=needed_time,
            exclude_ids=used_ids,
        )

        if not filler_steps:
            logger.warning(
                "루틴 %d: 보충 스텝 없음, 시간 미달 유지 (%d초)",
                routine_order,
                current_time,
            )
            return steps

        # 병합 후 stepOrder 재정렬
        combined = steps + filler_steps
        new_total = sum(s.limitTime for s in combined)

        logger.info(
            "루틴 %d: 스텝 %d개 추가, %d초 → %d초",
            routine_order,
            len(filler_steps),
            current_time,
            new_total,
        )

        return self._reorder_steps(combined)

    def _trim_steps_to_fit(
        self, steps: list[RoutineStep], routine_order: int, total_time: int
    ) -> list[RoutineStep]:
        """
        최대 시간을 초과할 경우 뒤에서부터 스텝 제거.

        Args:
            steps: 원본 스텝 목록
            routine_order: 루틴 순서 (로깅용)
            total_time: 현재 총 시간

        Returns:
            시간 조정된 스텝 목록 (stepOrder 재정렬됨)

        Raise:
        - None
        """
        trimmed_steps: list[RoutineStep] = []
        current_time = 0

        for step in steps:
            if current_time + step.limitTime > self.MAX_ROUTINE_TIME:
                # 최대 시간 초과 시 중단
                break
            trimmed_steps.append(step)
            current_time += step.limitTime

        removed_count = len(steps) - len(trimmed_steps)
        logger.warning(
            "루틴 %d: 총 시간 %d초 → %d초로 조정 (최대 %d초 초과, 스텝 %d개 제거)",
            routine_order,
            total_time,
            current_time,
            self.MAX_ROUTINE_TIME,
            removed_count,
        )

        # stepOrder 재정렬
        return [
            RoutineStep(
                exerciseId=step.exerciseId,
                type=step.type,
                stepOrder=idx + 1,
                limitTime=step.limitTime,
                durationTime=step.durationTime,
                targetReps=step.targetReps,
            )
            for idx, step in enumerate(trimmed_steps)
        ]

    def _create_response(
        self, validated_routines: list[Routine], task_id: str
    ) -> RecommendationResponseV1:
        """
        검증 & 보완된 루틴으로 응답 객체 생성

        Raise:
        - None
        """
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
