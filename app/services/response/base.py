# app/services/response/base.py

"""
추천 응답 빌더 - 공통 로직
- RoutineList 유효성 검증
- 유효성 미충족 시 보완 프로세스
- 버전별 빌더(V1/V2)가 상속하여 사용
"""

from __future__ import annotations

import logging

from app.core.config import RoutineTimePolicy
from app.core.exceptions import RoutineValidationError
from app.domain.exercise import ExerciseType
from app.domain.routine import Routine, RoutineList, RoutineStep
from app.domain.routinestep_factory import (
    copy_routine_step,
    create_routinestep_from_exercise,
    find_bilateral_pair,
)
from app.schemas.common import UserSurvey
from app.services.recommend.rule_based_recommender import RuleBasedRecommender

logger = logging.getLogger(__name__)


class CoreResponseBuilder:
    """
    루틴 검증 + 보정 공통 로직

    동작 흐름:
    1. 비즈니스 규칙 기반 유효성 검증
    2. 유효성 미충족 시 보완 프로세스
    3. 검증된 루틴 리스트 반환 (응답 래핑은 서브클래스 책임)
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

        # 0. exerciseId, _fallback_recommender 준비
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

        # 1. exerciseId → type 매핑 (데이터 일치 검증용)
        self._exercise_type_by_id: dict[int, ExerciseType] = {
            ex.exerciseId: ex.type for ex in exercise_repository._exercises
        }

        # 2. exerciseId → BaseExercise 매핑 (양측 운동 짝 추가용)
        self._exercise_by_id = {ex.exerciseId: ex for ex in exercise_repository._exercises}

        # 3. build_core() 호출 시 설정되는 임시 상태 (filler 스텝 추가 시 BodyPart 우선순위 적용)
        self._sorted_parts: list[tuple] | None = None

    def build_core(self, output: RoutineList, survey: UserSurvey) -> list[Routine]:
        """
        RoutineList을 검증하고 validated routines 반환.
        실패 시 rule-based fallback 시도.

        Args:
        - output: LLM 또는 rule-based 추천 결과
        - survey: 사용자 설문 데이터

        Returns:
        - list[Routine]: 검증 완료된 루틴 목록

        Raise:
        - RoutineValidationError: 검증 실패 및 fallback도 실패 시
        """
        # BodyPart 우선순위 추출 (filler 스텝 추가 시 사용)
        pain_scores = self._fallback_recommender._extract_pain_scores(survey)
        self._sorted_parts = sorted(pain_scores.items(), key=lambda x: x[1], reverse=True)

        try:
            return self._validate_and_fix(output.routines)

        except RoutineValidationError as e:  # fallback: Rule-Based
            if survey:
                logger.warning("LLM 루틴 검증 실패, rule-based fallback 시도: %s", e)
                fallback_output = self._fallback_recommender.recommend_routines(survey)
                return self._validate_and_fix(fallback_output.routines)

            # survey가 없으면 fallback 불가, re-raise
            raise

    # ============================================================
    # 검증 메서드
    # ============================================================

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
            validated.append(fixed_routine)

        logger.info("루틴 검증 완료: %d개 루틴", len(validated))
        return validated

    def _validate_single_routine(self, routine: Routine, routine_order: int) -> Routine:
        """
        단일 루틴 검증 및 보완

        1. 스텝 유효성 검증
        2. exerciseId 유효성 검증
        3. 그 exerciseId의 운동 데이터가 실제 정보와 일치하는지
        3-a. EYES + body part 혼합 루틴 필터링 (EYES 우선, body 제거 후 reason 초기화)
        3-b. EYES 전용 루틴 스텝 수 상한 적용 (최대 1개)
        4. Bilateral Exercise Rule 준수 여부
        5. PoseReferenceSpec.totalDuration == RoutineStep.durationTime 검증 및 맞추기
        6. limitTime 검증
        7. stepOrder 연속성 검증

        Raise:
        - RoutineValidationError: _filter_valid_exercises 에서 스텝 다 삭제된 경우
        """
        # 1. 스텝 유효성 검증
        steps = routine.steps
        if not steps:
            raise RoutineValidationError(
                f"루틴 {routine_order}에 스텝이 없습니다.", invalid_routines=[routine_order]
            )

        # 2. exerciseId 유효성 검증
        if self._valid_exercise_ids:
            steps = self._filter_valid_exercises(steps, routine.routineOrder)

        # 3. exerciseId의 운동 데이터 type 및 각각의 field rule 검증
        steps = self._validate_exercise_data(steps, routine.routineOrder)

        # 3-a. EYES + body part 혼합 루틴 필터링 (EYES 우선, body 제거)
        steps, mixed_converted = self._validate_eyes_mixing(steps, routine_order)

        # 3-b. EYES 전용 루틴 스텝 수 상한 적용 (최대 1개)
        steps = self._validate_eyes_step_count(steps, routine_order)

        # 4. Bilateral Exercise Rule 준수 여부 검증 및 보정 (+/-)
        fixed_steps = self._validate_bilateral_exercise_rule(steps, routine_order)

        # 5. PoseReferenceSpec.totalDuration == RoutineStep.durationTime 검증 및 맞추기
        fixed_steps = self._validate_duration_time(fixed_steps, routine_order)

        # 6. limitTime 총합 검증 및 조정 (+/-)
        fixed_steps = self._validate_total_time(fixed_steps, routine_order)

        # 7. stepOrder 재정렬 (1부터 연속)
        fixed_steps = self._reorder_steps(fixed_steps)

        # routineOrder 보정
        # 혼합 루틴이 EYES 전용으로 변환된 경우 reason을 기본값으로 초기화
        reason = (
            "눈 피로 해소를 위한 눈 운동 루틴입니다." if mixed_converted else routine.reason
        )
        return Routine(
            routineOrder=routine_order,
            reason=reason,
            steps=fixed_steps,
        )

    def _filter_valid_exercises(
        self, steps: list[RoutineStep], routine_order: int
    ) -> list[RoutineStep]:
        """
        유효하지 않은 exerciseId를 가진 스텝 필터링

        Raise:
        - RoutineValidationError: 유효한 스텝이 하나도 없음
        """
        valid_steps = []

        for step in steps:
            if step.exerciseId in self._valid_exercise_ids:  # type: ignore
                valid_steps.append(step)
            else:
                logger.warning(
                    "루틴 %d: 유효하지 않은 exerciseId 제거: %s",
                    routine_order,
                    step.exerciseId,
                )

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
        1. type 일치 검증 (DURATION | REPS | EYES)
        2. DURATION / REPS 각각의 필드 규칙 검증

        Raise:
        - RoutineValidationError: 유효한 스텝이 하나도 없음
        """

        validated: list[RoutineStep] = []

        for step in steps:
            # 1-a. exerciseId 존재 여부 검증
            if step.exerciseId not in self._exercise_type_by_id:
                logger.warning(
                    "루틴 %d: exerciseId %d가 운동 데이터에 존재하지 않음",
                    routine_order,
                    step.exerciseId,
                )
                continue

            expected_type = self._exercise_type_by_id[step.exerciseId]

            # 1-b. type 일치 검증
            if step.type != expected_type:
                logger.warning(
                    "루틴 %d: exerciseId %d의 type 불일치 (step: %s, expected: %s)",
                    routine_order,
                    step.exerciseId,
                    step.type,
                    expected_type,
                )
                continue

            # 2. DURATION/REPS 규칙 검증 및 보정
            if step.type == ExerciseType.DURATION and step.durationTime is None:
                logger.warning(
                    "루틴 %d: exerciseId %d - DURATION 타입인데 durationTime 누락, 기본값 적용",
                    routine_order,
                    step.exerciseId,
                )
                step = copy_routine_step(
                    step, duration_time=RoutineTimePolicy.DEFAULT_DURATION_TIME
                )

            if step.type == ExerciseType.REPS and step.targetReps is None:
                logger.warning(
                    "루틴 %d: exerciseId %d - REPS 타입인데 targetReps 누락, 기본값 적용",
                    routine_order,
                    step.exerciseId,
                )
                step = copy_routine_step(step, target_reps=RoutineTimePolicy.DEFAULT_TARGET_REPS)

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

        - 짝 운동이 이미 있으면: 그대로 유지
        - 짝 운동이 없으면: 해당 스텝 바로 뒤에 반대쪽 운동을 추가
        - 짝을 찾을 수 없으면: 해당 스텝 제거
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

            # 짝 운동 스텝 생성 및 추가
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
        DURATION 타입 운동의 durationTime을 PoseReferenceSpec.totalDuration과 일치하도록 검증 및 보정.

        Raises:
        - RoutineValidationError: 운동 정보가 없거나 pose가 없는 경우
        """
        result_steps: list[RoutineStep] = []

        for step in steps:
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

            first_pose_data = next(iter(exercise.pose.values()), None)
            if not isinstance(first_pose_data, dict) or "totalDuration" not in first_pose_data:
                raise RoutineValidationError(
                    f"루틴 {routine_order}: exerciseId {step.exerciseId}의 pose에 totalDuration이 없습니다.",
                    invalid_routines=[routine_order],
                )

            expected_duration = first_pose_data["totalDuration"]

            if step.durationTime == expected_duration:
                result_steps.append(step)
                continue

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

    def _is_eyes_only_routine(self, steps: list[RoutineStep]) -> bool:
        """EYES 전용 루틴인지 판별 (모든 스텝이 EYES 타입)"""
        for step in steps:
            exercise = self._exercise_by_id.get(step.exerciseId)

            if exercise is None or exercise.type != ExerciseType.EYES:
                return False

        return len(steps) > 0

    def _validate_eyes_mixing(
        self, steps: list[RoutineStep], routine_order: int
    ) -> tuple[list[RoutineStep], bool]:
        """
        EYES 타입과 body part 타입이 혼합된 루틴에서 body 스텝 제거 (EYES 우선).

        - EYES + body part 혼합 루틴: body 스텝 제거 후 EYES 스텝만 유지
        - EYES 전용 또는 body part 전용 루틴: 그대로 반환

        Returns:
        - (steps, mixed_converted): 보정된 스텝 리스트, 혼합 → EYES 전용으로 변환됐는지 여부
        """
        eyes_steps = [
            s for s in steps
            if self._exercise_type_by_id.get(s.exerciseId) == ExerciseType.EYES
        ]
        body_steps = [
            s for s in steps
            if self._exercise_type_by_id.get(s.exerciseId) != ExerciseType.EYES
        ]

        if eyes_steps and body_steps:
            logger.warning(
                "루틴 %d: EYES + body part 혼합 루틴 감지 - body 스텝 %d개 제거, EYES 스텝 %d개 유지",
                routine_order,
                len(body_steps),
                len(eyes_steps),
            )
            return eyes_steps, True

        return steps, False

    def _validate_eyes_step_count(
        self, steps: list[RoutineStep], routine_order: int
    ) -> list[RoutineStep]:
        """
        EYES 전용 루틴의 스텝 수를 1개로 제한.

        - EYES 전용 루틴에서 스텝이 2개 이상이면 첫 번째 스텝만 유지
        - EYES 전용 루틴이 아니면 그대로 반환
        """
        if not self._is_eyes_only_routine(steps):
            return steps

        if len(steps) <= 1:
            return steps

        logger.warning(
            "루틴 %d: EYES 전용 루틴 스텝 수 초과 (%d개) - 첫 번째 스텝만 유지",
            routine_order,
            len(steps),
        )
        return steps[:1]

    def _validate_total_time(
        self, steps: list[RoutineStep], routine_order: int
    ) -> list[RoutineStep]:
        """
        루틴 총 시간 검증 및 조정.

        - EYES 전용 루틴은 시간 정책 적용하지 않음 (pose 구조가 다르므로 별도 처리)
        - 목표 범위: MIN ~ MAX
        - 초과 시: 뒤에서부터 스텝 제거
        - 미달 시: rule-based 스텝 추가로 보충
        """
        # EYES 전용 루틴은 body part 시간 정책을 적용하지 않음
        if self._is_eyes_only_routine(steps):
            logger.debug("루틴 %d: EYES 전용 루틴, 시간 정책 스킵", routine_order)
            return steps

        total_time = sum(step.limitTime for step in steps)

        if self.MIN_ROUTINE_TIME <= total_time <= self.MAX_ROUTINE_TIME:
            logger.debug("루틴 %d: 총 시간 %d초 (범위 내, 조정 불필요)", routine_order, total_time)
            return steps

        if total_time > self.MAX_ROUTINE_TIME:
            return self._trim_steps_to_fit(steps, routine_order, total_time)

        return self._fill_time_gap(steps, routine_order, total_time)

    def _fill_time_gap(
        self, steps: list[RoutineStep], routine_order: int, current_time: int
    ) -> list[RoutineStep]:
        """시간 미달 시 rule-based 스텝 추가로 보충."""
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

        combined = steps + filler_steps
        new_total = sum(s.limitTime for s in combined)

        logger.info(
            "루틴 %d: 스텝 %d개 추가, %d초 → %d초",
            routine_order,
            len(filler_steps),
            current_time,
            new_total,
        )

        return combined

    def _trim_steps_to_fit(
        self, steps: list[RoutineStep], routine_order: int, total_time: int
    ) -> list[RoutineStep]:
        """최대 시간 초과 시 뒤에서부터 스텝 제거 (양측 운동 규칙 준수)"""
        default_step_time = 60
        excess_time = total_time - self.MAX_ROUTINE_TIME
        result = list(steps)
        removed_time = 0

        while removed_time < excess_time and result:
            last_step = result[-1]
            time_still_needed = excess_time - removed_time

            if last_step.side is None:
                result.pop()
                removed_time += last_step.limitTime
            else:
                if time_still_needed >= 2 * default_step_time:
                    result.pop()
                    removed_time += last_step.limitTime
                    if result and result[-1].side is not None:
                        popped = result.pop()
                        removed_time += popped.limitTime
                else:
                    non_bilateral_idx = None
                    for i in range(len(result) - 1, -1, -1):
                        if result[i].side is None:
                            non_bilateral_idx = i
                            break

                    if non_bilateral_idx is not None:
                        popped = result.pop(non_bilateral_idx)
                        removed_time += popped.limitTime
                    else:
                        if len(result) >= 2:
                            popped1 = result.pop()
                            popped2 = result.pop()
                            removed_time += popped1.limitTime + popped2.limitTime

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

        return [copy_routine_step(step, step_order=idx + 1) for idx, step in enumerate(result)]

    def _reorder_steps(self, steps: list[RoutineStep]) -> list[RoutineStep]:
        """stepOrder를 1부터 연속으로 재정렬"""
        return [copy_routine_step(step, step_order=idx + 1) for idx, step in enumerate(steps)]
