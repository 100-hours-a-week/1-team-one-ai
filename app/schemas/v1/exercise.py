# app/schemas/v1/exercise.py
"""
운동 데이터 스키마 (v1)
- class Exercise(BaseModel)
"""

from pydantic import ConfigDict, Field

from app.domain.exercise import BaseExercise, BodyPart, PoseReferenceSpec


class Exercise(BaseExercise):
    """
    운동 메타데이터 스키마
    - 추천, 루틴, 사용자 맥락과 분리된 '순수 운동 정의'
    - 단, 필드들의 스키마가 바뀔 수 있어 버전 분리함
    """

    model_config = ConfigDict(extra="ignore")

    bodyPart: BodyPart = Field(..., description="주 사용 부위")
    pose: dict[str, PoseReferenceSpec] = Field(default_factory=dict, description="운동 자세 정보")
