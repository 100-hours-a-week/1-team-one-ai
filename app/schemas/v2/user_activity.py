# app/schemas/v2/user_activity.py
"""
coreBE 배치 스케줄러로부터 받는 사용자 활동 프로필 스키마.

coreBE가 DB에서 직접 집계한 결과를 POST /api/v2/update/users 로 전송합니다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BodyPartRatios(BaseModel):
    """신체 부위별 운동 비율 (합계 ≈ 1.0)"""

    neck: float = 0.0
    shoulder: float = 0.0
    lowerBack: float = 0.0
    wrist: float = 0.0
    eyes: float = 0.0


class ExerciseTypeRatios(BaseModel):
    """운동 유형별 비율 (합계 ≈ 1.0)"""

    DURATION: float = 0.0
    REPS: float = 0.0
    EYES: float = 0.0


class DifficultyRatios(BaseModel):
    """난이도별 완료 비율 (합계 ≈ 1.0). JSON 키는 "1", "2", "3"."""

    model_config = ConfigDict(populate_by_name=True)

    level_1: float = Field(0.0, alias="1")
    level_2: float = Field(0.0, alias="2")
    level_3: float = Field(0.0, alias="3")


class UserProfile(BaseModel):
    """단일 사용자 집계 프로필."""

    userId: int
    bodyPartRatios: BodyPartRatios
    exerciseTypeRatios: ExerciseTypeRatios
    difficultyRatios: DifficultyRatios
    weeklyFrequency: int


class BatchProfileRequest(BaseModel):
    """POST /api/v2/update/users 요청 바디."""

    profiles: list[UserProfile]


class BatchProfileResponse(BaseModel):
    """POST /api/v2/update/users 응답 바디."""

    status: str
    upserted: int
