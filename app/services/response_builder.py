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
from app.core.exceptions import RoutineValidationError
from app.schemas.common import ExerciseType
from app.schemas.v1.request import UserSurvey
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
from app.utils.routine_step_converter import (
    copy_routine_step,
    create_routinestep_from_exercise,
    find_bilateral_pair,
)

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
        valid_exercise_ids: frozenset[int] | None = None,
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

        # exerciseId → type 매핑 (데이터 일치 검증용)
        self._exercise_type_by_id: dict[int, str] = {
            ex.exerciseId: ex.type for ex in exercise_repository._exercises
        }

        # exerciseId → Exercise 매핑 (양측 운동 짝 추가용)
        self._exercise_by_id = {ex.exerciseId: ex for ex in exercise_repository._exercises}

        self._fallback_recommender = (
            fallback_recommender
            if fallback_recommender is not None
            else RuleBasedRecommender(exercise_repository.raw_data)
        )

        # build() 호출 시 설정되는 임시 상태 (filler 스텝 추가 시 BodyPart 우선순위 적용)
        self._sorted_parts: list[tuple] | None = None

    def build(
        self, output: LLMRoutineOutput, task_id: str, survey: UserSurvey
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
        # BodyPart 우선순위 추출 (filler 스텝 추가 시 사용)
        pain_scores = self._fallback_recommender._extract_pain_scores(survey)
        self._sorted_parts = sorted(pain_scores.items(), key=lambda x: x[1], reverse=True)

        try:
            validated_routines = self._validate_and_fix(output.routines)
            return self._create_response(validated_routines, task_id=task_id)

        except RoutineValidationError as e:  # fallback: Rule-Based
            if survey:
                logger.warning("LLM 루틴 검증 실패, rule-based fallback 시도: %s", e)
                fallback_output = self._fallback_recommender.recommend_routines(survey)

                # Validate fallback output
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
        4. exerciseId의 운동 데이터가 실제 정보와 일치하는지
        5. Bilateral Exercise Rule 준수 여부
        6. stepOrder가 연속적인지

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

    def _validate_single_routine(self, routine: Routine, routine_order: int) -> Routine:
        """
        단일 루틴 검증 및 보완
        1. 스텝 유효성 검증
        2. exerciseId 유효성 검증
        3. 그 exerciseId의 운동 데이터가 실제 정보와 일치하는지
        4. Bilateral Exercise Rule 준수 여부
        5. ReferencePose.totalDuration == RoutineStep.durationTime 검증 및 맞추기
        6. limitTime 검증
        7. stepOrder 연속성 검증

        Input:
        - routine: 검증할 루틴
        - routine_order: 예상 루틴 순서

        Raise:
        - RoutineValidationError: _filter_valid_exercises 에서 스텝 다 삭제된 경우
        """
        # 1. 스텝 유효성 검증
        steps = routine.steps  # list[RoutineStep]
        if not steps:
            raise RoutineValidationError(
                f"루틴 {routine_order}에 스텝이 없습니다.", invalid_routines=[routine_order]
            )

        # 2. exerciseId 유효성 검증
        if self._valid_exercise_ids:
            steps = self._filter_valid_exercises(steps, routine.routineOrder)
            # steps: 유효한 exerciseId를 가진 스텝 목록
            # raise RoutineValidationError if all steps removed

        # 3. exerciseId의 운동 데이터 type 및 각각의 field rule 검증
        steps = self._validate_exercise_data(steps, routine.routineOrder)

        # 4. Bilateral Exercise Rule 준수 여부 검증 및 보정 (+/-)
        fixed_steps = self._validate_bilateral_exercise_rule(steps, routine_order)

        # 5. ReferencePose.totalDuration == RoutineStep.durationTime 검증 및 맞추기
        fixed_steps = self._validate_duration_time(fixed_steps, routine_order)

        # 6. limitTime 총합 검증 및 조정 (+/-)
        fixed_steps = self._validate_total_time(fixed_steps, routine_order)

        # 7. stepOrder 재정렬 (1부터 연속)
        fixed_steps = self._reorder_steps(fixed_steps)

        # routineOrder 보정
        return Routine(
            routineOrder=routine_order,
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

    def _validate_exercise_data(
        self, steps: list[RoutineStep], routine_order: int
    ) -> list[RoutineStep]:
        """
        1. type 일치 검증
        2. DURATION / REPS 각각의 필드 규칙 검증
            1. DURATION: durationTime is not null
            2. REPS: targetReps is not null

        Args:
        - steps: 검증할 스텝 목록
        - routine_order: 루틴 순서 (로깅용)

        Returns:
        - 일치하는 스텝 목록
        """
        validated: list[RoutineStep] = []

        for step in steps:
            expected_type = self._exercise_type_by_id.get(step.exerciseId)

            # 1. type 일치 검증
            if not expected_type or step.type != expected_type:
                logger.warning(
                    "루틴 %d: exerciseId %d의 type 불일치 (step: %s, expected: %s)",
                    routine_order,
                    step.exerciseId,
                    step.type,
                    expected_type or "N/A",
                )
                continue

            # 2. DURATION/REPS 규칙 검증
            if step.type == ExerciseType.DURATION and step.durationTime is None:
                logger.warning(
                    "루틴 %d: exerciseId %d - DURATION 타입인데 durationTime이 없음",
                    routine_order,
                    step.exerciseId,
                )
                continue

            if step.type == ExerciseType.REPS and step.targetReps is None:
                logger.warning(
                    "루틴 %d: exerciseId %d - REPS 타입인데 targetReps가 없음",
                    routine_order,
                    step.exerciseId,
                )
                continue

            validated.append(step)

        if not validated:
            raise RoutineValidationError(
                f"루틴 {routine_order}의 모든 스텝이 유효하지 않은 exerciseId로 제거되었습니다.",
                invalid_routines=[routine_order],
            )

        return validated

    def _validate_bilateral_exercise_rule(
        self, steps: list[RoutineStep], routine_order: int
    ) -> list[RoutineStep]:
        """
        양측 운동 규칙 검증 및 보정

        양측 운동(side가 설정된 운동)의 경우, 반대쪽 운동도 함께 있어야 함.
        - 짝 운동이 이미 있으면: 그대로 유지
        - 짝 운동이 없으면: 해당 스텝 바로 뒤에 반대쪽 운동을 추가
        - 짝을 찾을 수 없으면: 해당 스텝 제거

        Args:
        - steps: 검증할 스텝 목록
        - routine_order: 루틴 순서 (로깅용)

        Returns:
        - 보정된 스텝 목록 (짝 운동 추가됨, stepOrder는 _reorder_steps에서 재정렬)
        """
        result_steps: list[RoutineStep] = []
        existing_exercise_ids = {step.exerciseId for step in steps}
        added_pair_ids: set[int] = set()
        removed_exercise_ids: set[int] = set()

        for step in steps:
            # 양측 운동이 아니면 바로 추가
            if step.side is None:
                result_steps.append(step)
                continue

            # 짝 운동 찾기
            exercise = self._exercise_by_id.get(step.exerciseId)
            pair_exercise = (
                find_bilateral_pair(exercise, self._exercise_by_id) if exercise else None
            )

            if pair_exercise is None:
                # 짝을 찾을 수 없으면 해당 스텝 제거 (추가하지 않음)
                removed_exercise_ids.add(step.exerciseId)
                logger.warning(
                    "루틴 %d: exerciseId %d - 유효한 짝 운동을 찾을 수 없어 제거",
                    routine_order,
                    step.exerciseId,
                )
                continue

            # 현재 step 추가
            result_steps.append(step)

            pair_id = pair_exercise.exerciseId

            # 짝이 이미 존재하거나 이미 추가했으면 pair 추가 스킵
            if pair_id in existing_exercise_ids or pair_id in added_pair_ids:
                continue

            # 짝 운동 스텝 생성 및 추가 (현재 step 바로 뒤에 append됨)
            pair_step = create_routinestep_from_exercise(
                pair_exercise,
                step_order=step.stepOrder + 1,
                limit_time=step.limitTime,
                duration_time=step.durationTime,
                target_reps=step.targetReps,
            )
            result_steps.append(pair_step)
            added_pair_ids.add(pair_id)

            logger.info(
                "루틴 %d: exerciseId %d의 짝 운동(ID=%d) 자동 추가",
                routine_order,
                step.exerciseId,
                pair_id,
            )

        if removed_exercise_ids:
            logger.info(
                "루틴 %d: 짝 운동 없는 %d개 스텝 제거 (IDs: %s)",
                routine_order,
                len(removed_exercise_ids),
                removed_exercise_ids,
            )

        return result_steps

    def _validate_duration_time(
        self, steps: list[RoutineStep], routine_order: int
    ) -> list[RoutineStep]:
        """
        DURATION 타입 운동의 durationTime을 ReferencePose.totalDuration과 일치하도록 검증 및 보정.

        Args:
        - steps: 검증할 스텝 목록
        - routine_order: 루틴 순서 (로깅용)

        Returns:
        - 보정된 스텝 목록

        Raises:
        - RoutineValidationError: 운동 정보가 없거나 pose가 없는 경우
        """
        result_steps: list[RoutineStep] = []

        for step in steps:
            # DURATION 타입이 아니면 그대로 추가
            if step.type != ExerciseType.DURATION:
                result_steps.append(step)
                continue

            exercise = self._exercise_by_id.get(step.exerciseId)
            if exercise is None:
                raise RoutineValidationError(
                    f"루틴 {routine_order}: exerciseId {step.exerciseId}에 해당하는 운동 정보가 없습니다.",
                    invalid_routines=[routine_order],
                )

            if not exercise.pose:
                raise RoutineValidationError(
                    f"루틴 {routine_order}: exerciseId {step.exerciseId}에 pose 정보가 없습니다.",
                    invalid_routines=[routine_order],
                )

            # pose dict에서 첫 번째 ReferencePose의 totalDuration 가져오기
            first_pose = next(iter(exercise.pose.values()), None)
            if first_pose is None:
                raise RoutineValidationError(
                    f"루틴 {routine_order}: exerciseId {step.exerciseId}의 pose가 비어있습니다.",
                    invalid_routines=[routine_order],
                )

            expected_duration = first_pose.totalDuration

            # durationTime이 일치하면 그대로 추가
            if step.durationTime == expected_duration:
                result_steps.append(step)
                continue

            # durationTime 보정
            logger.info(
                "루틴 %d: exerciseId %d의 durationTime 보정 (%s → %d)",
                routine_order,
                step.exerciseId,
                step.durationTime,
                expected_duration,
            )
            corrected_step = copy_routine_step(step, duration_time=expected_duration)
            result_steps.append(corrected_step)

        return result_steps

    def _validate_total_time(
        self, steps: list[RoutineStep], routine_order: int
    ) -> list[RoutineStep]:
        """
        루틴 총 시간 검증 및 조정.

        - 목표 범위: 150 ~ 210초
        - 초과 시: 뒤에서부터 스텝 제거 (_trim_steps_to_fit)
        - 미달 시: rule-based 스텝 추가로 보충 (_fill_time_gap)

        Args:
        - steps: 검증할 스텝 목록
        - routine_order: 루틴 순서 (로깅용)

        Returns:
        - 조정된 스텝 목록
        """
        total_time = sum(step.limitTime for step in steps)

        # 범위 내: 그대로 반환
        if self.MIN_ROUTINE_TIME <= total_time <= self.MAX_ROUTINE_TIME:
            logger.debug("루틴 %d: 총 시간 %d초 (범위 내, 조정 불필요)", routine_order, total_time)
            return steps

        # 시간 초과: 뒤에서부터 스텝 제거
        if total_time > self.MAX_ROUTINE_TIME:
            return self._trim_steps_to_fit(steps, routine_order, total_time)

        # 시간 미달: rule-based 스텝 추가
        return self._fill_time_gap(steps, routine_order, total_time)

    def _fill_time_gap(
        self, steps: list[RoutineStep], routine_order: int, current_time: int
    ) -> list[RoutineStep]:
        """
        시간 미달 시 rule-based 스텝 추가로 보충.

        Args:
        - steps: 기존 스텝 목록
        - routine_order: 루틴 순서 (로깅용)
        - current_time: 현재 총 시간

        Returns:
        - 보충된 스텝 목록 (stepOrder 재정렬됨)
        """
        needed_time = self.MIN_ROUTINE_TIME - current_time
        used_ids = {step.exerciseId for step in steps}

        filler_steps = self._fallback_recommender.get_filler_steps(
            target_time=needed_time,
            exclude_ids=used_ids,
            sorted_parts=self._sorted_parts,
        )

        if not filler_steps:
            logger.warning(
                "루틴 %d: 보충 스텝 없음, 시간 미달 유지 (%d초)",
                routine_order,
                current_time,
            )
            return steps

        # 병합
        combined = steps + filler_steps
        new_total = sum(s.limitTime for s in combined)

        logger.info(
            "루틴 %d: 스텝 %d개 추가, %d초 → %d초",
            routine_order,
            len(filler_steps),
            current_time,
            new_total,
        )

        return combined  # reorder 책임은 분리

    def _trim_steps_to_fit(
        self, steps: list[RoutineStep], routine_order: int, total_time: int
    ) -> list[RoutineStep]:
        """
        최대 시간을 초과할 경우 뒤에서부터 스텝 제거 (양측 운동 규칙 준수)

        양측 운동 규칙:
        - 마지막 운동이 bilateral이고, 삭제해야 할 시간이 2개분 이상: 마지막 2개 삭제
        - 마지막 운동이 bilateral이고, 삭제해야 할 시간이 1개분 이상: non-bilateral 찾아서 삭제
        - 모든 스텝이 bilateral이면: 마지막 2개 삭제 후 non-bilateral 1개 추가

        Args:
            steps: 원본 스텝 목록
            routine_order: 루틴 순서 (로깅용)
            total_time: 현재 총 시간

        Returns:
            시간 조정된 스텝 목록 (stepOrder 재정렬됨)
        """
        default_step_time = 60  # 기본 스텝 시간
        excess_time = total_time - self.MAX_ROUTINE_TIME
        result = list(steps)
        removed_time = 0

        while removed_time < excess_time and result:
            last_step = result[-1]
            time_still_needed = excess_time - removed_time

            if last_step.side is None:
                # Non-bilateral: 단순 제거
                result.pop()
                removed_time += last_step.limitTime
            else:
                # Bilateral: 규칙 적용
                if time_still_needed >= 2 * default_step_time:
                    # 2개분 시간 이상 필요: 마지막 2개 (bilateral pair) 삭제
                    result.pop()
                    removed_time += last_step.limitTime
                    if result and result[-1].side is not None:
                        popped = result.pop()
                        removed_time += popped.limitTime
                else:
                    # 1개분 시간 필요: non-bilateral 찾아서 삭제
                    non_bilateral_idx = None
                    for i in range(len(result) - 1, -1, -1):
                        if result[i].side is None:
                            non_bilateral_idx = i
                            break

                    if non_bilateral_idx is not None:
                        popped = result.pop(non_bilateral_idx)
                        removed_time += popped.limitTime
                    else:
                        # 모든 스텝이 bilateral: 마지막 2개 삭제 후 non-bilateral 1개 추가
                        if len(result) >= 2:
                            popped1 = result.pop()
                            popped2 = result.pop()
                            removed_time += popped1.limitTime + popped2.limitTime

                            # Non-bilateral filler 추가
                            used_ids = {s.exerciseId for s in result}
                            filler_steps = self._fallback_recommender.get_filler_steps(
                                target_time=default_step_time,
                                exclude_ids=used_ids,
                                sorted_parts=self._sorted_parts,
                            )
                            if filler_steps:
                                result.append(filler_steps[0])
                                removed_time -= filler_steps[0].limitTime

                            logger.info(
                                "루틴 %d: 모든 스텝이 bilateral - 2개 삭제 후 non-bilateral 1개 추가",
                                routine_order,
                            )
                        else:
                            # 스텝이 1개만 남음
                            popped = result.pop()
                            removed_time += popped.limitTime

        final_time = sum(s.limitTime for s in result)
        removed_count = len(steps) - len(result)
        logger.warning(
            "루틴 %d: 총 시간 %d초 → %d초로 조정 (최대 %d초 초과, 스텝 %d개 제거)",
            routine_order,
            total_time,
            final_time,
            self.MAX_ROUTINE_TIME,
            removed_count,
        )

        # stepOrder 재정렬
        return [copy_routine_step(step, step_order=idx + 1) for idx, step in enumerate(result)]

    def _reorder_steps(self, steps: list[RoutineStep]) -> list[RoutineStep]:
        """
        stepOrder를 1부터 연속으로 재정렬

        Raise:
        - None
        """
        return [copy_routine_step(step, step_order=idx + 1) for idx, step in enumerate(steps)]

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
