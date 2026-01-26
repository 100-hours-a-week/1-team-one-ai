# app/api/v1/data.py

"""
운동 데이터 관리 API
- POST /exercises/update: 운동 데이터 강제 업데이트
"""

import logging

from fastapi import APIRouter

from app.core.exceptions import AppError
from app.data.loader import exercise_repository, fetch_and_save_exercises

logger = logging.getLogger(__name__)

router = APIRouter()


class ExerciseDataError(AppError):
    """운동 데이터 처리 실패 - 500"""

    error_code = "EXERCISE_DATA_ERROR"


@router.post("/exercises/update")
async def update_exercises() -> dict:
    """
    운동 데이터를 외부 API에서 다시 가져와 로드.

    Returns:
        200: {"status": "ok", "count": N}
        500: {"code": "EXERCISE_DATA_ERROR", "errors": [...]}
    """
    try:
        fetch_and_save_exercises()
    except Exception as e:
        logger.error("운동 데이터 fetch 실패: %s", e)
        raise ExerciseDataError(f"운동 데이터 fetch 실패: {e}") from e

    try:
        exercise_repository.load()

    except Exception as e:
        logger.error("운동 데이터 reload 실패: %s", e)
        raise ExerciseDataError(f"운동 데이터 reload 실패: {e}") from e

    return {"status": "ok", "count": len(exercise_repository.exercise_ids)}
