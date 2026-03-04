# app/api/v2/data.py

"""
임베딩용 데이터 관리 API
- POST /update/users    : coreBE 배치 집계 프로필 수신 → 벡터DB upsert (Qdrant 미연결 시 silent skip)
- POST /update/exercises: 운동 데이터 강제 업데이트 + 벡터DB upsert (Qdrant 미연결 시 silent skip)

TODO: 아래 책임 분리 및 모듈화 검토
- _create_exercise_vector_service
- _create_user_activity_vector_service
- ExerciseVectorService 싱글턴
- UserActivityVectorService 싱글턴
"""

import logging

from fastapi import APIRouter

from app.core.config import settings
from app.core.exceptions import ExerciseDataError
from app.data.loader import exercise_repository, fetch_and_save_exercises
from app.schemas.v2.user_activity import BatchProfileRequest
from app.services.exercise_vector_service import ExerciseVectorService
from app.services.user_activity_vector_service import UserActivityVectorService

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# ExerciseVectorService 싱글턴
# ============================================================


def _create_exercise_vector_service() -> ExerciseVectorService:
    """
    ExerciseVectorService 싱글턴 생성.

    - Qdrant 연결 실패 또는 임베딩 모델 로드 실패 시 WARNING 후 비활성화 상태로 반환
    - 비활성화 상태에서 try_upsert_all() 호출 시 조용히 건너뜀 (API 영향 없음)

    환경변수:
      QDRANT_URL              : 연결 대상 (기본 http://localhost:6333)
      QDRANT_API_KEY          : 클라우드 인스턴스용 (로컬 생략)
      QDRANT_EMBEDDING_MODEL  : 임베딩 모델명 (기본 intfloat/multilingual-e5-small)
    """
    try:
        from sentence_transformers import SentenceTransformer

        from app.data.exercise_vector_repository import QdrantExerciseVectorRepository
        from app.data.qdrant_client import get_qdrant_client

        client = get_qdrant_client()
        model = SentenceTransformer(settings.QDRANT_EMBEDDING_MODEL)
        # TODO: 임베딩 모델 다양화 - 로컬 SentenceTransformer / 클라우드 API 선택적 사용
        exercise_vector_repo = QdrantExerciseVectorRepository(client)
        logger.info(
            "ExerciseVectorService 초기화 완료 [url=%s, model=%s]",
            settings.QDRANT_URL,
            settings.QDRANT_EMBEDDING_MODEL,
        )
        return ExerciseVectorService(repository=exercise_vector_repo, embedding_model=model)

    except Exception as e:
        logger.warning("ExerciseVectorService 초기화 실패 — 벡터 upsert 비활성화: %s", e)
        return ExerciseVectorService(repository=None, embedding_model=None)


# ExerciseVectorService (운동 벡터DB) 싱글턴
# TODO: 싱글톤(싱글턴) 중앙 집중 관리
_exercise_vector_service = _create_exercise_vector_service()


# ============================================================
# UserActivityVectorService 싱글턴
# ============================================================


def _create_user_activity_vector_service() -> UserActivityVectorService:
    """
    UserActivityVectorService 싱글턴 생성.

    - Qdrant 연결 실패 또는 임베딩 모델 로드 실패 시 WARNING 후 비활성화 상태로 반환
    - 비활성화 상태에서 try_upsert_batch() 호출 시 조용히 건너뜀 (API 영향 없음)

    환경변수:
      QDRANT_URL              : 연결 대상 (기본 http://localhost:6333)
      QDRANT_API_KEY          : 클라우드 인스턴스용 (로컬 생략)
      QDRANT_EMBEDDING_MODEL  : 임베딩 모델명 (기본 intfloat/multilingual-e5-small)
    """
    try:
        from sentence_transformers import SentenceTransformer

        from app.data.qdrant_client import get_qdrant_client
        from app.data.user_activity_repository import QdrantUserActivityVectorRepository

        client = get_qdrant_client()
        model = SentenceTransformer(settings.QDRANT_EMBEDDING_MODEL)
        # TODO: 임베딩 모델 다양화 - 로컬 SentenceTransformer / 클라우드 API 선택적 사용
        user_vector_repo = QdrantUserActivityVectorRepository(client)
        logger.info(
            "UserActivityVectorService 초기화 완료 [url=%s, model=%s]",
            settings.QDRANT_URL,
            settings.QDRANT_EMBEDDING_MODEL,
        )
        return UserActivityVectorService(repository=user_vector_repo, embedding_model=model)

    except Exception as e:
        logger.warning("UserActivityVectorService 초기화 실패 — 벡터 upsert 비활성화: %s", e)
        return UserActivityVectorService(repository=None, embedding_model=None)


# UserActivityVectorService (사용자 활동 벡터DB) 싱글턴
# TODO: 싱글톤(싱글턴) 중앙 집중 관리
_user_activity_vector_service = _create_user_activity_vector_service()


# ============================================================
# API Endpoints
# ============================================================


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
    result = _exercise_vector_service.try_upsert_all(exercise_repository.raw_data)

    return {"status": "ok", "count": len(exercise_repository.exercise_ids), "state": result.state}


@router.post("/update/users")
async def update_users(body: BatchProfileRequest) -> dict:
    """
    coreBE 배치 스케줄러로부터 집계된 사용자 활동 프로필을 수신하여 벡터DB upsert.

    흐름:
    1. coreBE가 DB 집계 후 배치 타이밍에 이 엔드포인트를 호출
    2. 각 프로필을 passage로 변환 → 임베딩 → Qdrant upsert
    3. Qdrant 미연결 시 WARNING 로그 후 silent skip (응답에 영향 없음)

    Returns:
        200: {"status": "ok", "upserted": N, "state": null | {"errorType": ..., "errorMessage": ...}}
    """
    result = _user_activity_vector_service.try_upsert_batch(body.profiles)
    return {"status": "ok", "upserted": result.upserted, "state": result.state}
