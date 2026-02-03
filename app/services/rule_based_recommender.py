# app/services/rule_based_recommender.py

"""
룰 기반 운동 추천 (LLM fallback)
- 설문 응답 기반 단순 매칭 로직
- LLM 실패 시 최소한의 추천 제공
"""

import logging

from app.core.config import RoutineTimePolicy
from app.schemas.v1.exercise import BodyPart, Exercise
from app.schemas.v1.request import UserSurvey
from app.schemas.v1.response import (
    LLMRoutineOutput,
    Routine,
    RoutineStep,
)
from app.utils.routine_step_converter import (
    create_routinestep_from_exercise,
    find_bilateral_pair,
)

logger = logging.getLogger(__name__)

# 설문 문항 키워드 → 부위 매핑
KEYWORD_TO_BODY_PART: dict[str, BodyPart] = {
    "목": BodyPart.NECK,
    "어깨": BodyPart.SHOULDER,
    "손목": BodyPart.WRIST,
    "허리": BodyPart.LOWER_BACK,
}

# 부위 → 한글 이름 매핑
BODY_PART_TO_KOREAN: dict[BodyPart, str] = {
    BodyPart.NECK: "목",
    BodyPart.SHOULDER: "어깨",
    BodyPart.WRIST: "손목",
    BodyPart.LOWER_BACK: "허리",
}


class RuleBasedRecommender:
    """
    룰 기반 추천기 / fallback

    1. 설문에서 통증 부위 추출 (키워드 매핑)
    2. 해당 부위 운동을 우선 선택하여
    3. limitTime 기준 total time 150~200으로 맞춰서 루틴 생성 x routineCount

    Instance Variables:
    - _exercises: 전체 운동 데이터
    - _exercises_by_part: 부위별 운동 데이터
    - _target_time: 목표 루틴 총 시간
    - _min_time: 최소 루틴 총 시간

    Public Methods:
    - recommend_routines: 설문 데이터를 기반으로 운동 루틴 추천
    - get_filler_steps: 루틴을 보완하기 위한 추가 운동 단계 가져오기

    Private Methods:
    - _group_by_body_part: 부위별 운동 그룹화
    - _extract_pain_scores: 설문 응답에서 부위별 통증 점수 추출
    - _create_step: 운동 데이터로 RoutineStep 생성
    - _create_routine: 단일 루틴 생성
    """

    def __init__(self, exercises: list[dict]) -> None:
        """
        운동 데이터 초기화 및 부위별 그룹화
        exercises = exercise_repository.raw_data (exercises.json)
        """
        self._exercises = [Exercise.model_validate(e) for e in exercises]
        self._exercises_by_id = {ex.exerciseId: ex for ex in self._exercises}
        self._exercises_by_part = self._group_by_body_part()
        self._target_time = RoutineTimePolicy.TARGET_TIME
        self._min_time = RoutineTimePolicy.MIN_TIME

        logger.debug(
            "RuleBasedRecommender 초기화: 총 %d개 운동 로드",
            len(self._exercises),
        )

    def _group_by_body_part(self) -> dict[BodyPart, list[Exercise]]:
        """
        운동을 부위별로 그룹화
        init 시 1회 수행
        """
        grouped: dict[BodyPart, list[Exercise]] = {part: [] for part in BodyPart}
        # grouped = {
        # BodyPart.NECK: list[Exercise],
        # ...
        # }
        for exercise in self._exercises:
            grouped[exercise.bodyPart].append(exercise)

        return grouped

    def _extract_pain_scores(self, survey: UserSurvey) -> dict[BodyPart, int]:
        """
        설문 응답에서 부위별 통증 점수 추출
        - init 시 1회 수행 (fill_time_gap 호출 시 필요)
        - recommend_routines 호출 시 1회 수행
        """
        scores: dict[BodyPart, int] = {}

        for answer in survey.survey:
            question = answer.questionContent
            score = answer.selectedOptionSortOrder

            for keyword, body_part in KEYWORD_TO_BODY_PART.items():
                if keyword in question:
                    # 같은 부위가 여러 번 나오면 최대값 사용
                    scores[body_part] = max(scores.get(body_part, 0), score)
                    break

        logger.debug(
            "[RuleBased] 통증 점수 추출: %s",
            {part.name: score for part, score in scores.items()},
        )
        return scores

    def _create_step(self, exercise: Exercise, step_order: int) -> RoutineStep:
        """
        운동 데이터로 RoutineStep 생성
        _create_routine에서 호출
        Exercise → RoutineStep 변환 및 bilateral exercise 처리
        """
        return create_routinestep_from_exercise(exercise, step_order)

    def _create_routine(
        self,
        routine_order: int,
        sorted_parts: list[tuple[BodyPart, int]],
    ) -> Routine:
        """
        단일 루틴 생성
        recommend_routines 호출 시 루틴 수 (routine_count) 만큼 수행
        """
        steps: list[RoutineStep] = []
        used_exercise_ids: set[int] = set()
        step_order = 1  # 단일 루틴 내 스텝 순서
        total_time = 0  # 단일 루틴 총 시간

        # 통증 부위 우선으로 운동 선택
        for body_part, _ in sorted_parts:
            if total_time >= self._target_time:
                break

            exercises = self._exercises_by_part.get(
                body_part, []
            )  # 통증 부위 순으로 운동 목록 load

            for exercise in exercises:
                if exercise.exerciseId in used_exercise_ids:
                    continue  # 이미 선택된 운동은 건너뜀

                step = self._create_step(exercise, step_order)
                steps.append(step)
                used_exercise_ids.add(exercise.exerciseId)
                step_order += 1
                total_time += step.limitTime

                if total_time >= self._target_time:
                    break

        # 루틴 최소 시간 확보 (부족하면 다른 부위에서 추가)
        if total_time < self._min_time:
            for exercise in self._exercises:
                if exercise.exerciseId in used_exercise_ids:
                    continue

                step = self._create_step(exercise, step_order)
                steps.append(step)
                used_exercise_ids.add(exercise.exerciseId)
                step_order += 1
                total_time += step.limitTime

                if total_time >= self._min_time:
                    break

        # 루틴 이유 생성
        if sorted_parts:
            top_part = sorted_parts[0][0]
            part_name = BODY_PART_TO_KOREAN.get(top_part, top_part.value)
            reason = f"{part_name} 부위 집중 케어를 위한 루틴입니다."
        else:
            reason = "전신 스트레칭을 위한 루틴입니다."

        logger.debug(
            "[RuleBased] 루틴 #%d 생성 완료 - 선택된 운동 IDs: %s, 총 시간: %d초",
            routine_order,
            [s.exerciseId for s in steps],
            total_time,
        )

        return Routine(
            routineOrder=routine_order,
            reason=reason,
            steps=steps,
        )

    def get_filler_steps(
        self,
        target_time: int,
        exclude_ids: set[int] | None = None,
        sorted_parts: list[tuple[BodyPart, int]] | None = None,
    ) -> list[RoutineStep]:
        """
        시간 보충용 스텝 생성 (양측 운동 규칙 준수)

        ResponseBuilder에서 루틴 시간이 최소 기준 미달일 때 호출.
        exclude_ids에 포함된 운동은 제외하고 target_time을 채울 수 있는 스텝 반환.

        양측 운동 규칙:
        - 추가하려는 운동이 bilateral이고, 남은 시간이 2개분 이상: bilateral 쌍 추가
        - 추가하려는 운동이 bilateral이고, 남은 시간이 2개분 미만: 스킵하고 non-bilateral 탐색

        Args:
        - target_time: 채워야 할 목표 시간 (초)
        - exclude_ids: 제외할 exerciseId 집합 (이미 루틴에 포함된 운동)
        - sorted_parts: BodyPart 우선순위 목록 (높은 순). None이면 전체 운동 순회.

        Returns:
        - list[RoutineStep]: 보충용 스텝 목록 (stepOrder는 1부터 시작, 호출측에서 재정렬 필요)
        """
        default_limit_time = 60  # RoutineStep 기본 limitTime
        exclude_ids = set(exclude_ids) if exclude_ids else set()
        steps: list[RoutineStep] = []
        current_time = 0
        step_order = 1

        # sorted_parts가 있으면 BodyPart 우선순위 순으로, 없으면 전체 운동 순회
        if sorted_parts:
            exercises_to_check = [
                ex
                for body_part, _ in sorted_parts
                for ex in self._exercises_by_part.get(body_part, [])
            ]
        else:
            exercises_to_check = self._exercises

        for exercise in exercises_to_check:
            if exercise.exerciseId in exclude_ids:
                continue

            if current_time >= target_time:
                break

            remaining_time = target_time - current_time
            pair_exercise = find_bilateral_pair(exercise, self._exercises_by_id)

            # 1. Bilateral exercise: 짝 운동 처리
            if pair_exercise is not None:
                if pair_exercise.exerciseId in exclude_ids:
                    # 짝이 이미 사용 중이면 스킵
                    continue

                pair_time = default_limit_time * 2  # 양측 운동 2개 시간

                if remaining_time >= pair_time:
                    # 2개분 시간 충분: bilateral 쌍 추가
                    step1 = self._create_step(exercise, step_order)
                    step2 = self._create_step(pair_exercise, step_order + 1)
                    steps.extend([step1, step2])
                    exclude_ids.add(exercise.exerciseId)
                    exclude_ids.add(pair_exercise.exerciseId)
                    current_time += pair_time
                    step_order += 2
                else:
                    # 2개분 시간 부족: 스킵하고 non-bilateral 계속 탐색
                    continue

            # 2. Non-Bilateral exercise: 바로 추가
            else:
                step = self._create_step(exercise, step_order)
                steps.append(step)
                exclude_ids.add(exercise.exerciseId)
                current_time += step.limitTime
                step_order += 1

        logger.debug(
            "Filler 스텝 생성: 목표 %d초, 결과 %d개 스텝 (%d초)",
            target_time,
            len(steps),
            current_time,
        )
        return steps

    def recommend_routines(self, survey: UserSurvey) -> LLMRoutineOutput:
        """
        설문 기반 룰 추천 실행.

        1. 설문에서 통증 부위 및 강도 추출
        2. 통증 강도 순으로 정렬 (높은 순)
        3. 루틴 생성 (통증 부위 우선순위 회전)
        4. 루틴 반환

        Returns:
        - LLMRoutineOutput: LLM 응답과 동일한 형식
        """
        # 1. 설문에서 통증 부위 및 강도 추출
        pain_scores = self._extract_pain_scores(survey)

        # 2. 통증 강도 순으로 정렬 (높은 순)
        sorted_parts = sorted(pain_scores.items(), key=lambda x: x[1], reverse=True)

        # 3. 루틴 생성
        routines = []
        routine_count = max(1, survey.routineCount)

        for i in range(routine_count):
            # 통증 부위 우선순위 회전
            rotated_parts = sorted_parts[i:] + sorted_parts[:i]

            routine = self._create_routine(
                routine_order=i + 1,
                sorted_parts=rotated_parts,
            )
            routines.append(routine)

        total_steps = sum(len(r.steps) for r in routines)
        logger.info(
            "룰 기반 추천 완료: %d개 루틴, 총 %d개 스텝",
            len(routines),
            total_steps,
        )

        # 첫 번째/두 번째 루틴 상세 출력 (디버깅용)
        if routines:
            first = routines[0]
            logger.debug(
                "[RuleBased] 루틴 #1 상세: reason='%s', exerciseIds=%s",
                first.reason,
                [s.exerciseId for s in first.steps],
            )
            if len(routines) > 1:
                second = routines[1]
                logger.debug(
                    "[RuleBased] 루틴 #2 상세: reason='%s', exerciseIds=%s",
                    second.reason,
                    [s.exerciseId for s in second.steps],
                )

        return LLMRoutineOutput(routines=routines)
