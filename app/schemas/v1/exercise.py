# app/schemas/v1/exercise.py
"""
운동 데이터 스키마 (v1)
- class BodyPart(str, Enum)
- class DifficultyLevel(int, Enum)
- class Exercise(BaseModel)
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ExerciseType


class BodyPart(str, Enum):
    """운동 종류: 운동 영향 부위"""

    NECK = "neck"
    SHOULDER = "shoulder"
    WRIST = "wrist"
    LOWER_BACK = "lowerBack"


class DifficultyLevel(int, Enum):
    """운동 난이도: 1~3의 정수 값"""

    EASY = 1
    NORMAL = 2
    HARD = 3


class Exercise(BaseModel):
    """
    운동 메타데이터 스키마
    - v1~v3까지 필드 변경 없이 유지되는 Core Domain Model
    - 추천, 루틴, 사용자 맥락과 분리된 '순수 운동 정의'
    """

    model_config = ConfigDict(frozen=True)

    exerciseId: str = Field(..., description="운동 고유 ID")
    name: str = Field(..., description="운동 이름")
    content: str = Field(..., description="운동 수행 방법 설명")
    effect: str = Field(..., description="운동 효과 설명")

    type: ExerciseType = Field(..., description="운동 수행 방식")
    bodyPart: BodyPart = Field(..., description="주 사용 부위")
    difficulty: DifficultyLevel = Field(..., description="난이도 (1~3)")

    tags: str = Field(..., description="운동 관련 태그 (comma-separated string)")
