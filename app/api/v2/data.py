# app/api/v2/data.py

"""
임베딩용 데이터 관리 API
- POST /update/users: 사용자 데이터 강제 업데이트
- POST /update/exercises: 운동 데이터 강제 업데이트
"""

import logging

from fastapi import APIRouter

from app.core.exceptions import AppError
from app.data.loader import exercise_repository, fetch_and_save_exercises

logger = logging.getLogger(__name__)

router = APIRouter()


class UserDataError(AppError):
    """사용자 데이터 fetch 실패 - 500"""

    error_code = "USER_DATA_ERROR"


class ExerciseDataError(AppError):
    """사용자 데이터 fetch 실패 - 500"""

    error_code = "EXERCISE_DATA_ERROR"


@router.post("/update/users")
async def update_users() -> dict:
    """
    사용자 데이터를 외부 API에서 다시 가져와 로드 & 벡터DB 업데이트.

    Returns:
        200: {"status": "ok", "count": N}
        500: {"code": "EXERCISE_DATA_ERROR", "errors": [...]}
    """
    try:
        # TODO:사용자 데이터 fetching & embedding - v2에서 사용하는 함수로 변경
        fetch_and_save_exercises()

    except Exception as e:
        logger.error("시용자 데이터 fetch 실패: %s", e)
        raise UserDataError(f"시용자 데이터 fetch 실패: {e}") from e

    try:
        exercise_repository.load()

    except Exception as e:
        logger.error("시용자 데이터 load 실패: %s", e)
        raise UserDataError(f"시용자 데이터 load 실패: {e}") from e

    # TODO: 리턴값도 user vector update에 걸맞게 수정
    return {"status": "ok", "count": len(exercise_repository.exercise_ids)}


@router.post("/update/exercises")
async def update_exercises() -> dict:
    """
    운동 데이터를 외부 API에서 다시 가져와 로드 & 벡터DB 업데이트.

    Returns:
        200: {"status": "ok", "count": N}
        500: {"code": "EXERCISE_DATA_ERROR", "errors": [...]}
    """
    try:
        # TODO:운동 데이터 fetching & embedding - v2에서 사용하는 함수로 변경
        fetch_and_save_exercises()

    except Exception as e:
        logger.error("운동 데이터 fetch 실패: %s", e)
        raise ExerciseDataError(f"운동 데이터 fetch 실패: {e}") from e

    try:
        exercise_repository.load()

    except Exception as e:
        logger.error("운동 데이터 load 실패: %s", e)
        raise ExerciseDataError(f"운동 데이터 load 실패: {e}") from e

    return {"status": "ok", "count": len(exercise_repository.exercise_ids)}
