# app/api/v2/data.py

"""
임베딩용 데이터 관리 API
- POST /update/users    : 사용자 데이터 강제 업데이트 (TODO: 사용자 벡터 upsert)
- POST /update/exercises: 운동 데이터 강제 업데이트 + 벡터DB upsert (Qdrant 미연결 시 silent skip)
"""

import logging

from fastapi import APIRouter

from app.core.exceptions import AppError
from app.data.loader import exercise_repository, fetch_and_save_exercises
from app.services.exercise_vector_service import ExerciseVectorService

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# ExerciseVectorService 싱글턴
# ============================================================


def _create_exercise_vector_service() -> ExerciseVectorService:
    """
    ExerciseVectorService 싱글턴 생성.

    TODO: Qdrant 연동 완료 후 아래 주석 해제 및 None → 실제 인스턴스로 교체:

        from sentence_transformers import SentenceTransformer
        from qdrant_client import QdrantClient
        from app.data.exercise_vector_repository import QdrantExerciseVectorRepository
        from app.core.config import settings

        client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
        model  = SentenceTransformer("snunlp/KR-ELECTRA-discriminator")
        repo   = QdrantExerciseVectorRepository(client)
        return ExerciseVectorService(repository=repo, embedding_model=model)
    """
    return ExerciseVectorService(repository=None, embedding_model=None)


_exercise_vector_service = _create_exercise_vector_service()


# ============================================================
# 에러 정의
# ============================================================


class UserDataError(AppError):
    """사용자 데이터 fetch 실패 - 500"""

    error_code = "USER_DATA_ERROR"


class ExerciseDataError(AppError):
    """운동 데이터 fetch 실패 - 500"""

    error_code = "EXERCISE_DATA_ERROR"


# ============================================================
# API Endpoints
# ============================================================


@router.post("/update/users")
async def update_users() -> dict:
    """
    사용자 데이터를 외부 API에서 다시 가져와 벡터DB 업데이트.

    Returns:
        200: {"status": "ok", "count": N}
        500: {"code": "USER_DATA_ERROR", "errors": [...]}
    """
    try:
        # TODO: 사용자 데이터 fetching & embedding - UserActivityService.build_and_upsert()로 교체
        fetch_and_save_exercises()

    except Exception as e:
        logger.error("사용자 데이터 fetch 실패: %s", e)
        raise UserDataError(f"사용자 데이터 fetch 실패: {e}") from e

    try:
        exercise_repository.load()

    except Exception as e:
        logger.error("사용자 데이터 load 실패: %s", e)
        raise UserDataError(f"사용자 데이터 load 실패: {e}") from e

    # TODO: 리턴값도 user vector update에 걸맞게 수정
    return {"status": "ok", "count": len(exercise_repository.exercise_ids)}


@router.post("/update/exercises")
async def update_exercises() -> dict:
    """
    운동 데이터를 외부 API에서 다시 가져와 로드 후 벡터DB upsert.

    흐름:
    1. coreBE에서 운동 데이터 fetch → exercises.json 저장
    2. exercise_repository 리로드 (LLM 프롬프트용 인메모리 캐시 갱신)
    3. 벡터DB upsert — Qdrant 미연결 시 WARNING 로그 후 silent skip (응답에 영향 없음)

    Returns:
        200: {"status": "ok", "count": N}
        500: {"code": "EXERCISE_DATA_ERROR", "errors": [...]}
    """
    # 1. fetch & save to JSON
    try:
        fetch_and_save_exercises()

    except Exception as e:
        logger.error("운동 데이터 fetch 실패: %s", e)
        raise ExerciseDataError(f"운동 데이터 fetch 실패: {e}") from e

    # 2. reload in-memory repository (기존 API 사용 캐시 갱신)
    try:
        exercise_repository.load()

    except Exception as e:
        logger.error("운동 데이터 load 실패: %s", e)
        raise ExerciseDataError(f"운동 데이터 load 실패: {e}") from e

    # 3. 벡터DB upsert (silent — Qdrant 미연결 시 건너뜀, 기존 흐름에 영향 없음)
    _exercise_vector_service.try_upsert_all(exercise_repository.raw_data)

    return {"status": "ok", "count": len(exercise_repository.exercise_ids)}
