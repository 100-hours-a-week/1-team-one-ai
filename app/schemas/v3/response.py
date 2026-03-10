# app/schemas/v3/response.py
"""
V3 응답 데이터 스키마 — app.schemas.task re-export
- class ProgressStep(str, Enum)
- class TaskAcceptedResponse(BaseModel)   — POST 202 즉시 응답
- class TaskResult(BaseModel)             — GET 폴링 응답 / coreBE 콜백 페이로드
"""

from app.schemas.task import (
    PROGRESS_STEP_PERCENTAGE,
    ProgressStep,
    TaskAcceptedResponse,
    TaskResult,
)

__all__ = [
    "PROGRESS_STEP_PERCENTAGE",
    "ProgressStep",
    "TaskAcceptedResponse",
    "TaskResult",
]
