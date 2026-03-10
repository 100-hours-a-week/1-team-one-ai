# app/api/v2/data.py
"""
임베딩용 데이터 관리 API (v2) — router + endpoints only

DI 배선은 app/api/deps.py 참조.
- POST /update/exercises: 운동 데이터 강제 업데이트 + 벡터DB upsert
- POST /update/users    : coreBE 배치 집계 프로필 수신 → 벡터DB upsert

두 엔드포인트 모두 Qdrant 오류 시 503, 컬렉션 오류 시 500을 반환한다.
"""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import get_exercise_vector_service, get_user_activity_vector_service
from app.core.exceptions import ExerciseDataError
from app.data.loader import exercise_repository, fetch_and_save_exercises
from app.data.qdrant_exceptions import upsert_error_to_http_status
from app.schemas.v2.user_activity import BatchProfileRequest
from app.services.exercise_vector_service import ExerciseVectorService
from app.services.user_activity_vector_service import UserActivityVectorService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/update/exercises", response_model=None)
async def update_exercises(
    exercise_svc: ExerciseVectorService = Depends(get_exercise_vector_service),
) -> dict | JSONResponse:
    """
    운동 데이터를 외부 API에서 다시 가져와 로드 후 벡터DB upsert.

    흐름:
    1. coreBE에서 운동 데이터 fetch → exercises.json 저장
    2. exercise_repository 리로드 (LLM 프롬프트용 인메모리 캐시 갱신)
    3. 벡터DB upsert — Qdrant 오류 시 503/500 반환

    Args:
    - exercise_svc: ExerciseVectorService (DI) → deps.get_exercise_vector_service

    Returns:
        200: {"status": "ok", "exercises": N, "upserted": N}
        500: {"code": "EXERCISE_DATA_ERROR", "errors": [...]} — fetch/load 실패
        503: {"status": "error", "upserted": 0, ...} — Qdrant 연결/인증/서버 오류
        500: {"status": "error", "upserted": 0, ...} — Qdrant 컬렉션 오류
    """
    try:
        fetch_and_save_exercises()
    except Exception as e:
        logger.error("운동 데이터 fetch 실패: %s", e)
        raise ExerciseDataError(f"운동 데이터 fetch 실패: {e}") from e

    try:
        exercise_repository.load()
    except Exception as e:
        logger.error("운동 데이터 load 실패: %s", e)
        raise ExerciseDataError(f"운동 데이터 load 실패: {e}") from e

    upserted = exercise_svc.try_upsert_all(exercise_repository.raw_data)
    body = {
        "status": "error" if upserted.error_type else "ok",
        "exercises": len(exercise_repository.exercise_ids),
        "upserted": upserted.upserted,
        "error": None
        if upserted.error_type is None
        else {"type": upserted.error_type, "message": upserted.error_message},
    }
    if upserted.error_type is not None:
        return JSONResponse(status_code=upsert_error_to_http_status(upserted.error_type), content=body)
    return body


@router.post("/update/users", response_model=None)
async def update_users(
    body: BatchProfileRequest,
    user_activity_svc: UserActivityVectorService = Depends(get_user_activity_vector_service),
) -> dict | JSONResponse:
    """
    coreBE 배치 스케줄러로부터 집계된 사용자 활동 프로필을 수신하여 벡터DB upsert.

    흐름:
    1. coreBE가 DB 집계 후 배치 타이밍에 이 엔드포인트를 호출
    2. 각 프로필을 passage로 변환 → 임베딩 → Qdrant upsert
    3. Qdrant 오류 시 503/500 반환

    Args:
    - body: 사용자 활동 프로필 배치 — userId별 bodyPartRatios, exerciseTypeRatios, difficultyRatios, weeklyFrequency
    - user_activity_svc: UserActivityVectorService (DI) → deps.get_user_activity_vector_service

    Returns:
        200: {"status": "ok", "upserted": N}
        503: {"status": "error", "upserted": 0, "error": {...}} — Qdrant 연결/인증/서버 오류
        500: {"status": "error", "upserted": 0, "error": {...}} — Qdrant 컬렉션 오류
    """
    upserted = user_activity_svc.try_upsert_batch(body.profiles)
    body_resp = {
        "status": "error" if upserted.error_type else "ok",
        "upserted": upserted.upserted,
        "error": None
        if upserted.error_type is None
        else {"type": upserted.error_type, "message": upserted.error_message},
    }
    if upserted.error_type is not None:
        return JSONResponse(status_code=upsert_error_to_http_status(upserted.error_type), content=body_resp)
    return body_resp
