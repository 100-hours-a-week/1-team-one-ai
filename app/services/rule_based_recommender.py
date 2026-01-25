# app/services/rule_based_recommender.py

"""
룰 기반 운동 추천 (LLM fallback)
- 설문 응답 기반 단순 매칭 로직
- LLM 실패 시 최소한의 추천 제공
"""

from app.core.config import RoutineTimePolicy
from app.schemas.common import ExerciseType
from app.schemas.v1.exercise import BodyPart, Exercise
from app.schemas.v1.request import UserSurvey
from app.schemas.v1.response import (
    LLMRoutineOutput,
    Routine,
    RoutineStep,
)

# 설문 문항 키워드 → 부위 매핑
KEYWORD_TO_BODY_PART: dict[str, BodyPart] = {
    "목": BodyPart.NECK,
    "어깨": BodyPart.SHOULDER,
    "손목": BodyPart.WRIST,
    "허리": BodyPart.LOWER_BACK,
}


class RuleBasedRecommender:
    """
    룰 기반 추천기

    1. 설문에서 통증 부위 추출 (키워드 매핑)
    2. 해당 부위 운동을 우선 선택하여
    3. limitTime 기준 total time 150~200으로 맞춰서 루틴 생성 x routineCount

    - 단순하지만 항상 동작하는 fallback
    """

    def __init__(self, exercises: list[dict]) -> None:
        """
        운동 데이터 초기화 및 부위별 그룹화
        exercises = exercise_repository.raw_data (exercises.json)
        """
        self._exercises = [Exercise.model_validate(e) for e in exercises]
        self._exercises_by_part = self._group_by_body_part()
        self._target_time = RoutineTimePolicy.TARGET_TIME
        self._min_time = RoutineTimePolicy.MIN_TIME

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
        recommend_routines 호출 시 1회 수행
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

        return scores

    def _create_step(self, exercise: Exercise, step_order: int) -> RoutineStep:
        """
        운동 데이터로 RoutineStep 생성
        _create_routine에서 호출

        1. 운동 유형에 따라 다른 파라미터 설정
            - DURATION: limitTime, durationTime
            - REPS: limitTime, targetReps

        2. 공통 파라미터 설정
            - 운동 ID: exerciseId
            - 단계 순서: stepOrder
        """
        ex_type = ExerciseType(exercise.type.value)

        if ex_type == ExerciseType.DURATION:
            return RoutineStep(
                exerciseId=exercise.exerciseId,
                type=ex_type,
                stepOrder=step_order,
                limitTime=60,
                durationTime=30,
                targetReps=None,
            )
        else:  # REPS
            return RoutineStep(
                exerciseId=exercise.exerciseId,
                type=ex_type,
                stepOrder=step_order,
                limitTime=60,
                durationTime=None,
                targetReps=10,
            )

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
        used_exercise_ids: set[str] = set()
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
            reason = f"{top_part.value} 부위 집중 케어를 위한 루틴입니다."
        else:
            reason = "전신 스트레칭을 위한 루틴입니다."

        return Routine(
            routineOrder=routine_order,
            reason=reason,
            steps=steps,
        )

    def get_filler_steps(
        self,
        target_time: int,
        exclude_ids: set[str] | None = None,
    ) -> list[RoutineStep]:
        """
        시간 보충용 스텝 생성.

        ResponseBuilder에서 루틴 시간이 최소 기준 미달일 때 호출.
        exclude_ids에 포함된 운동은 제외하고 target_time을 채울 수 있는 스텝 반환.

        Args:
        - target_time: 채워야 할 목표 시간 (초)
        - exclude_ids: 제외할 exerciseId 집합 (이미 루틴에 포함된 운동)

        Returns:
        - list[RoutineStep]: 보충용 스텝 목록 (stepOrder는 1부터 시작, 호출측에서 재정렬 필요)
        """
        exclude_ids = exclude_ids or set()
        steps: list[RoutineStep] = []
        current_time = 0
        step_order = 1

        for exercise in self._exercises:
            if exercise.exerciseId in exclude_ids:
                continue

            if current_time >= target_time:
                break

            step = self._create_step(exercise, step_order)
            steps.append(step)
            current_time += step.limitTime
            step_order += 1

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

        return LLMRoutineOutput(routines=routines)
