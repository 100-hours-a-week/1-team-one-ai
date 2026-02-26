# app/domain/exercise.py
"""
공통 운동 도메인
"""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ExerciseType(str, Enum):
    """운동 수행 방식"""

    REPS = "REPS"
    DURATION = "DURATION"
    EYES = "EYES"


class DifficultyLevel(int, Enum):
    """운동 난이도: 1~3의 정수 값"""

    EASY = 1
    NORMAL = 2
    HARD = 3


class BodyPart(str, Enum):
    """운동 영향 부위 (전 버전 공통 superset)"""

    NECK = "neck"
    SHOULDER = "shoulder"
    WRIST = "wrist"
    LOWER_BACK = "lowerBack"
    EYES = "eyes"


class Side(str, Enum):
    """
    양측 운동 방향 (Bilateral Exercise)
    - LEFT
    - RIGHT
    """

    LEFT = "left"
    RIGHT = "right"


class PoseReferenceSpec(BaseModel):
    """
    운동 자세 참조 정보
    """

    model_config = ConfigDict(extra="ignore")

    targetKeypoints: list[int] = Field(..., description="타겟 키포인트")
    keyframes: list[dict] = Field(..., description="키프레임 정보")
    totalDuration: int = Field(..., description="총 지속 시간 (초)")
    fpsHint: Optional[int] = Field(None, description="프레임 속도 힌트")


class BaseExercise(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    exerciseId: int = Field(..., alias="id", description="운동 고유 ID")
    name: str = Field(..., description="운동 이름")
    content: str = Field(..., description="운동 수행 방법 설명")
    effect: str = Field(..., description="운동 효과 설명")

    difficulty: DifficultyLevel = Field(..., description="난이도 (1~3)")
    tags: str = Field(..., description="운동 관련 태그 (comma-separated string)")
    type: ExerciseType = Field(..., description="운동 수행 방식: REPS / DURATION / EYES")

    bodyPart: BodyPart = Field(..., description="주 사용 부위")
    pose: Any = Field(..., description="운동 자세 정보 (버전별 타입 상이)")
