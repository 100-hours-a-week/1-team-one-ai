# app/utils/routine_step_converter.py

"""
RoutineStep 변환 유틸리티
- Exercise → RoutineStep 중앙 집중식 변환
- Bilateral exercise 처리 (왼쪽/오른쪽 파싱)
- RoutineStep 복사 (stepOrder 변경 시 사용)
"""

from typing import Optional

from app.schemas.common import ExerciseType, Side
from app.schemas.v1.exercise import Exercise
from app.schemas.v1.response import RoutineStep


def parse_side(name: str) -> Optional[Side]:
    """
    운동 이름에서 방향(왼쪽/오른쪽) 파싱

    Args:
        name: 운동 이름 (예: "목 측굴 스트레칭 (왼쪽)")

    Returns:
        Side.LEFT, Side.RIGHT, or None
    """
    if "(왼쪽)" in name:
        return Side.LEFT
    if "(오른쪽)" in name:
        return Side.RIGHT
    return None


def find_bilateral_pair(
    exercise: Exercise,
    exercise_by_id: dict[int, Exercise],
) -> Optional[Exercise]:
    """
    양측 운동의 짝 운동 찾기

    규칙: 연속된 ID가 짝 (예: 52=오른쪽, 53=왼쪽)
    일반적으로 오른쪽이 먼저지만, 양쪽 방향 모두 확인

    Args:
    - exercise: 현재 운동
    - exercise_by_id: exerciseId → Exercise 매핑

    Returns:
    - 짝 운동 Exercise (양측 운동이 아니거나 짝이 없으면 None)
    """
    side = parse_side(exercise.name)
    if side is None:
        return None

    # 기본 규칙: RIGHT+1=LEFT, LEFT-1=RIGHT
    if side == Side.RIGHT:
        candidates = [exercise.exerciseId + 1, exercise.exerciseId - 1]
    else:  # LEFT
        candidates = [exercise.exerciseId - 1, exercise.exerciseId + 1]

    for candidate_id in candidates:
        pair_exercise = exercise_by_id.get(candidate_id)
        if pair_exercise:
            pair_side = parse_side(pair_exercise.name)
            # 반대쪽이어야 유효한 짝
            if pair_side is not None and pair_side != side:
                return pair_exercise

    return None


def create_routinestep_from_exercise(
    exercise: Exercise,
    step_order: int,
    limit_time: int = 60,
    duration_time: Optional[int] = None,
    target_reps: Optional[int] = None,
) -> RoutineStep:
    """
    Exercise → RoutineStep 변환

    운동 유형에 따라 기본값 적용:
    - DURATION: durationTime=30, targetReps=None
    - REPS: durationTime=None, targetReps=10

    Args:
    - exercise: 변환할 운동 데이터
    - step_order: 루틴 내 순서
    - limit_time: 제한 시간 (초), 기본값 60
    - duration_time: 지속 시간 (DURATION 타입 시 사용), None이면 기본값 적용
    - target_reps: 목표 반복 횟수 (REPS 타입 시 사용), None이면 기본값 적용

    Returns:
    - 변환된 RoutineStep
    """
    ex_type = ExerciseType(exercise.type.value)
    side = parse_side(exercise.name)

    if ex_type == ExerciseType.DURATION:
        return RoutineStep(
            exerciseId=exercise.exerciseId,
            type=ex_type,
            stepOrder=step_order,
            limitTime=limit_time,
            durationTime=duration_time if duration_time is not None else 30,
            targetReps=None,
            side=side,
        )
    else:  # REPS
        return RoutineStep(
            exerciseId=exercise.exerciseId,
            type=ex_type,
            stepOrder=step_order,
            limitTime=limit_time,
            durationTime=None,
            targetReps=target_reps if target_reps is not None else 10,
            side=side,
        )


def copy_routine_step(
    step: RoutineStep,
    step_order: Optional[int] = None,
) -> RoutineStep:
    """
    RoutineStep 복사 (stepOrder 변경 시 사용)

    Args:
    - step: 복사할 RoutineStep
    - step_order: 새로운 stepOrder (None이면 기존 값 유지)

    Returns:
    - 복사된 RoutineStep
    """
    return RoutineStep(
        exerciseId=step.exerciseId,
        type=step.type,
        stepOrder=step_order if step_order is not None else step.stepOrder,
        limitTime=step.limitTime,
        durationTime=step.durationTime,
        targetReps=step.targetReps,
        side=step.side,
    )
