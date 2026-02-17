# app/schemas/v2/exercise.py
"""
운동 데이터 스키마 (v2)
- class EyeReferenceSpec(BaseModel)
- class BodyPoseWrapper(BaseModel)
- class EyePoseWrapper(BaseModel)
- class Exercise(BaseModel)
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.domain.exercise import BaseExercise, BodyPart, PoseReferenceSpec


class EyeReferenceSpec(BaseModel):
    """
    눈운동 기준 정의 (시선 기반)
    v2+ 에만 존재
    """

    model_config = ConfigDict(extra="ignore")

    keyFrames: list[dict] = Field(..., description="시선 이동 시퀀스")
    totalDurationMs: int = Field(..., ge=0, description="전체 운동 시간(ms)")


class BodyPoseWrapper(BaseModel):
    kind: Literal["BODY"]
    data: PoseReferenceSpec


class EyePoseWrapper(BaseModel):
    kind: Literal["EYES"]
    data: EyeReferenceSpec


class Exercise(BaseExercise):
    """
    운동 메타데이터 스키마 v2
    """

    bodyPart: BodyPart = Field(..., description="주 사용 부위 - EYES 추가")
    pose: BodyPoseWrapper | EyePoseWrapper = Field(..., description="운동 자세 정보 - EYES 추가")

    @model_validator(mode="before")
    def infer_pose_type(cls, values):
        pose = values.get("pose")
        body_part = values.get("bodyPart")

        if pose is None:
            raise ValueError("Pose 데이터가 누락되었습니다.")

        try:
            if isinstance(pose, dict) and ("keyFrames" in pose or "totalDurationMs" in pose):
                values["pose"] = EyePoseWrapper(
                    kind="EYES",
                    data=EyeReferenceSpec.model_validate(pose),
                )
                return values

            if body_part == BodyPart.EYES:
                values["pose"] = EyePoseWrapper(
                    kind="EYES", data=EyeReferenceSpec.model_validate(pose)
                )
                return values

            # else or Default
            values["pose"] = BodyPoseWrapper(
                kind="BODY",
                data=PoseReferenceSpec.model_validate(pose.get("referencePose", pose)),
            )
            return values

        except ValidationError as e:
            raise ValueError(f"pose 스키마가 bodyPart={body_part}와 일치하지 않습니다.") from e
