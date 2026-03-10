# app/services/exercise_vector_service.py
"""
운동 벡터 upsert 서비스

ExerciseVectorService
  - try_upsert_all(exercises) → UpsertResult
    - passage 생성 → 임베딩 → PointStruct 구성 → repository.upsert_all()
    - Qdrant 미연결 / embedding_model 미설정 시 UpsertResult(error_type=CONNECTION) 반환
    - 예외 발생 시 에러 타입 포함 UpsertResult 반환
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from qdrant_client import models

from app.data.qdrant_exceptions import (
    QdrantAuthError,
    QdrantCollectionError,
    QdrantConnectionError,
    QdrantError,
    QdrantServerError,
    UpsertErrorType,
    UpsertResult,
)

if TYPE_CHECKING:
    from app.data.exercise_vector_repository import ExerciseVectorRepository

logger = logging.getLogger(__name__)


# ── passage 생성 ──────────────────────────────────────────────────────────────


def _build_passage(ex: dict) -> str:
    """
    운동 dict → 임베딩용 자연어 passage.

    설문 query와 동일한 의미 공간에 사영되도록 동일한 prefix(passage:)를 사용합니다.
    """
    return (
        f"passage: 운동명: {ex['name']} | "
        f"부위: {ex['bodyPart']} | "
        f"효과: {ex['effect']} | "
        f"태그: {ex['tags']}"
    )


# ── ExerciseVectorService ─────────────────────────────────────────────────────


class ExerciseVectorService:
    """
    운동 데이터 → (Qdrant) 벡터 upsert 오케스트레이터.
    1. repository: (Qdrant)ExerciseVectorRepository
    2. embedding_model: SentenceTransformer
    3. try_upsert_all

    - embedding_model 또는 repository 가 None 이면 CONNECTION error UpsertResult 반환
    - upsert 도중 예외 발생 시 에러 타입 포함 UpsertResult 반환
    """

    def __init__(
        self,
        repository: ExerciseVectorRepository | None,
        embedding_model: Any | None,  # SentenceTransformer 등 encode() 지원 모델
    ) -> None:
        self._repository = repository
        self._embedding_model = embedding_model

    # ── public ────────────────────────────────────────────────────────────────

    def try_upsert_all(self, exercises: list[dict]) -> UpsertResult:
        """
        운동 목록 전체를 벡터DB에 upsert 합니다.

        - Qdrant 미연결 / 모델 미설정 시: CONNECTION error UpsertResult 반환
        - 실행 중 예외 발생 시: 에러 타입 포함 UpsertResult 반환
        - 기존 운동 데이터(exercises.json) 로드 흐름과 완전히 독립적으로 동작
        """
        if self._repository is None or self._embedding_model is None:
            missing = ", ".join(
                label
                for flag, label in [
                    (self._repository is None, "Qdrant 미연결"),
                    (self._embedding_model is None, "임베딩 모델 미설정"),
                ]
                if flag
            )
            logger.warning("ExerciseVectorService: %s — 벡터 upsert 불가", missing)
            return UpsertResult(
                upserted=0,
                error_type=UpsertErrorType.CONNECTION,
                error_message=missing,
            )

        try:
            points = self._build_points(exercises)
            count = self._repository.upsert_all(points)
            logger.info("exercises 벡터 upsert 완료: %d 개", count)
            return UpsertResult(upserted=count)

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

    # ── private ───────────────────────────────────────────────────────────────

    def _build_points(self, exercises: list[dict]) -> list[models.PointStruct]:
        """
        운동 list[dict] → list[PointStruct].

        payload:
          - bodyPart, type, difficulty: 필터 검색용
          - completion_rate: 운동 자체의 평균 완료율
            TODO: coreBE 집계 데이터(exercise_results)로 실제 완료율 계산
                  현재는 전부 1.0 으로 초기화
        """
        points = []
        for ex in exercises:
            passage = _build_passage(ex)
            vector: list[float] = self._embedding_model.encode(passage).tolist()  # type: ignore

            point = models.PointStruct(
                id=ex["id"],  # exerciseId (int)
                vector=vector,
                payload={
                    "bodyPart": ex["bodyPart"],
                    "type": ex["type"],
                    "difficulty": ex["difficulty"],
                    "completion_rate": 1.0,  # TODO: 운동별 평균 완료율로 교체
                },
            )
            points.append(point)

        return points
