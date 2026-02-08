# app/schemas/v2/exercise.py
"""
운동 데이터 스키마 (v2)
- class BodyPart(str, Enum)
- class DifficultyLevel(int, Enum)
- class Exercise(BaseModel)
"""

# from enum import Enum
# from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ExerciseType
from app.schemas.v1.exercise import BodyPart, DifficultyLevel, ReferencePose


class Exercise(BaseModel):
    """
    운동 메타데이터 스키마
    """

    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    exerciseId: int = Field(..., alias="id", description="운동 고유 ID")
    type: ExerciseType = Field(..., description="운동 수행 방식")
    name: str = Field(..., description="운동 이름")
    content: str = Field(..., description="운동 수행 방법 설명")
    effect: str = Field(..., description="운동 효과 설명")

    bodyPart: BodyPart = Field(..., description="주 사용 부위")
    difficulty: DifficultyLevel = Field(..., description="난이도 (1~3)")
    tags: str = Field(..., description="운동 관련 태그 (comma-separated string)")

    pose: dict[str, ReferencePose] = Field(default_factory=dict, description="운동 자세 정보")
