# app/services/user_activity/user_activity_vector_service.py
"""
사용자 활동 프로필 벡터 upsert 서비스.

UserActivityVectorService
  - try_upsert_batch(profiles) → UpsertResult
    - passage 생성 → 임베딩 → repository.upsert()
    - Qdrant 미연결 / embedding_model 미설정 시 UpsertResult(upserted=0) 반환 (silent skip)
    - 예외 발생 시 에러 타입 포함 UpsertResult 반환
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.data.user_activity_repository import UserActivityVectorRepository

from app.data.qdrant_exceptions import (
    QdrantAuthError,
    QdrantCollectionError,
    QdrantConnectionError,
    QdrantError,
    QdrantServerError,
    UpsertErrorType,
    UpsertResult,
)
from app.schemas.v2.user_activity import UserProfile

logger = logging.getLogger(__name__)

MIN_RATIO = 0.1  # passage 생성 시 포함할 최소 비율 임계값
# TODO: Constants 중앙 집중 관리 - app/core/constants.py 등 별도 모듈로 이동 검토


# ── passage 생성 ──────────────────────────────────────────────────────────────


def _build_passage(profile: UserProfile) -> str:
    """
    집계된 사용자 프로필 → 임베딩용 자연어 passage.

    exercises passage와 동일한 의미 공간에 사영되도록 동일한 prefix(passage:)를 사용합니다.
    MIN_RATIO 미만 항목은 노이즈로 간주하여 제외합니다.
    """
    bp = profile.bodyPartRatios.model_dump()
    et = profile.exerciseTypeRatios.model_dump()
    dd = {
        "1": profile.difficultyRatios.level_1,
        "2": profile.difficultyRatios.level_2,
        "3": profile.difficultyRatios.level_3,
    }

    dominant_parts = [f"{k}({v})" for k, v in bp.items() if v >= MIN_RATIO]
    dominant_types = [f"{k}({v})" for k, v in et.items() if v >= MIN_RATIO]
    dominant_diffs = [f"{k}({v})" for k, v in dd.items() if v >= MIN_RATIO]

    return (
        f"passage: "
        f"주요 운동 부위: {', '.join(dominant_parts)} | "
        f"선호 운동 유형: {', '.join(dominant_types)} | "
        f"적합 난이도: {', '.join(dominant_diffs)} | "
        f"주간 운동 빈도: {profile.weeklyFrequency}회"
    )


# ── UserActivityVectorService ─────────────────────────────────────────────────


class UserActivityVectorService:
    """
    사용자 활동 프로필 → (Qdrant) 벡터 upsert 오케스트레이터.
    1. repository: (Qdrant)UserActivityVectorRepository
        - upsert
        - exists
    2. embedding_model: SentenceTransformer
    3. try_upsert_batch

    - embedding_model 또는 repository 가 None 이면 debug 로그 후 UpsertResult(upserted=0) 반환
    - upsert 도중 예외 발생 시 에러 타입 포함 UpsertResult 반환 (기존 API 흐름 영향 없음)
    """

    def __init__(
        self,
        repository: UserActivityVectorRepository | None,
        embedding_model: Any | None,  # SentenceTransformer 등 encode() 지원 모델
    ) -> None:
        self._repository = repository
        self._embedding_model = embedding_model

    def try_upsert_batch(self, profiles: list[UserProfile]) -> UpsertResult:
        """
        사용자 프로필 목록을 벡터DB에 upsert 합니다.

        - Qdrant 미연결 / 모델 미설정 시: DEBUG 로그 후 UpsertResult(upserted=0) 반환
        - 실행 중 예외 발생 시: 에러 타입 포함 UpsertResult 반환
        """
        if self._repository is None or self._embedding_model is None:
            logger.debug(
                "UserActivityVectorService: repository=%s, embedding_model=%s — 벡터 upsert 건너뜀",
                "설정됨" if self._repository else "미설정",
                "설정됨" if self._embedding_model else "미설정",
            )
            return UpsertResult(upserted=0)

        try:
            for profile in profiles:
                passage = _build_passage(profile)
                vector: list[float] = self._embedding_model.encode(passage).tolist()  # type: ignore
                payload = {
                    "bodyPartRatios": profile.bodyPartRatios.model_dump(),
                    "exerciseTypeRatios": profile.exerciseTypeRatios.model_dump(),
                    "difficultyRatios": {
                        "1": profile.difficultyRatios.level_1,
                        "2": profile.difficultyRatios.level_2,
                        "3": profile.difficultyRatios.level_3,
                    },
                    "weeklyFrequency": profile.weeklyFrequency,
                }
                self._repository.upsert(profile.userId, vector, payload)

            logger.info("user activity 벡터 upsert 완료: %d 명", len(profiles))
            return UpsertResult(upserted=len(profiles))

        except QdrantAuthError as e:
            logger.error("Qdrant 인증 실패 — API 키 확인 필요: %s", e, exc_info=True)
            return UpsertResult(upserted=0, error_type=UpsertErrorType.AUTH, error_message=str(e))
        except QdrantServerError as e:
            logger.error("Qdrant 서버 5xx 오류 (status=%d): %s", e.status_code, e, exc_info=True)
            return UpsertResult(upserted=0, error_type=UpsertErrorType.SERVER, error_message=f"status={e.status_code}")
        except QdrantCollectionError as e:
            logger.warning("Qdrant 컬렉션 없음 — 컬렉션 생성 전 upsert 시도: %s", e)
            return UpsertResult(upserted=0, error_type=UpsertErrorType.COLLECTION, error_message=str(e))
        except QdrantConnectionError as e:
            logger.warning("Qdrant 연결 실패 — 서버 상태 확인 필요: %s", e)
            return UpsertResult(upserted=0, error_type=UpsertErrorType.CONNECTION, error_message=str(e))
        except QdrantError as e:
            logger.error("Qdrant 알 수 없는 오류: %s", e, exc_info=True)
            return UpsertResult(upserted=0, error_type=UpsertErrorType.UNKNOWN, error_message=str(e))
