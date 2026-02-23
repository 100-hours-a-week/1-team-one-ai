# app/domain/routine.py
"""
공통 루틴 도메인
"""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.exercise import ExerciseType, Side


class RoutineStep(BaseModel):
    """
    루틴 내 단일 운동 스텝
    """

    exerciseId: int = Field(..., description="운동 ID")
    type: ExerciseType = Field(..., description="운동 수행 방식 REPS | DURATION | EYES")
    stepOrder: int = Field(..., ge=1, description="루틴 내 순서")
    limitTime: int = Field(..., ge=0, description="해당 스텝 제한 시간(초)")
    durationTime: Optional[int] = Field(
        None, ge=0, description="지속 시간 기반 운동일 경우 수행 시간(초)"
    )
    targetReps: Optional[int] = Field(
        None, ge=0, description="횟수 기반 운동일 경우 목표 반복 횟수"
    )
    side: Optional[Side] = Field(None, description="양측 운동의 경우 방향 (왼쪽/오른쪽)")

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def check_exercise_type_fields(self) -> "RoutineStep":
        if self.type == ExerciseType.REPS:
            if self.targetReps is None:
                raise ValueError("REPS 타입 운동은 targetReps가 필수입니다.")
            if self.durationTime is not None:
                raise ValueError("REPS 타입 운동은 durationTime을 가질 수 없습니다.")

        elif self.type == ExerciseType.DURATION:
            if self.durationTime is None:
                raise ValueError("DURATION 타입 운동은 durationTime이 필수입니다.")
            if self.targetReps is not None:
                raise ValueError("DURATION 타입 운동은 targetReps를 가질 수 없습니다.")

        elif self.type == ExerciseType.EYES:
            if self.durationTime is not None:
                raise ValueError("EYES 타입 운동은 durationTime을 가질 수 없습니다.")
            if self.targetReps is not None:
                raise ValueError("EYES 타입 운동은 targetReps를 가질 수 없습니다.")

        return self


class Routine(BaseModel):
    """
    추천된 루틴 1개:
    "steps": List[RoutineStep] 포함
    """

    routineOrder: int = Field(..., ge=1, description="루틴 순서")
    reason: str = Field(..., description="루틴 구성 이유")
    steps: List[RoutineStep] = Field(..., description="루틴에 포함된 운동 스텝 목록")

    @model_validator(mode="after")
    def check_steps_not_empty(self) -> "Routine":
        if not self.steps:
            raise ValueError("루틴은 최소 1개 이상의 step을 포함해야 합니다.")
        return self


class RoutineList(BaseModel):
    """
    LLM이 출력하는 JSON 구조
    {"routines": List[Routine]}
    """

    routines: List[Routine]
