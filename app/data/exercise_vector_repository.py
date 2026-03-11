# app/data/exercise_vector_repository.py
"""
운동 벡터 저장소

ExerciseVectorRepository (Protocol)
  - upsert_all(points) → int

QdrantExerciseVectorRepository
  - 컬렉션이 없으면 자동 생성 (벡터 차원은 첫 포인트에서 추론)
  - Cosine 유사도 기준 #TODO: 향후 거리 기준을 컬렉션 단위로 유연하게 설정할 수 있도록 개선 가능
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from qdrant_client import QdrantClient, models

from app.data.qdrant_exceptions import translate_qdrant_error

logger = logging.getLogger(__name__)

COLLECTION_NAME = "exercises"


# ── Protocol ───────────────────────────────────────────────────────────


@runtime_checkable
class ExerciseVectorRepository(Protocol):
    def upsert_all(self, points: list[models.PointStruct]) -> int:
        """
        운동 벡터 포인트를 벡터DB에 batch upsert 합니다.

        Returns:
        - upsert된 포인트 수
        """
        ...

    def search(
        self,
        query_vector: list[float],
        limit: int = 20,
        score_threshold: float = 0.5,
    ) -> list[models.ScoredPoint]:
        """
        쿼리 벡터와 유사한 운동을 검색합니다.

        Returns:
        - 유사도 순으로 정렬된 ScoredPoint 목록
        """
        ...


# ── Interface ──────────────────────────────────────────────────────────


class QdrantExerciseVectorRepository(ExerciseVectorRepository):
    """
    ExerciseVectorRepository의 Qdrant 구현체.

    - upsert_all 최초 호출 시 컬렉션 자동 생성 (존재하면 skip)
    - 벡터 차원은 첫 번째 포인트의 vector 길이에서 추론
    - 거리 기준: Cosine (시맨틱 유사도)
    """

    def __init__(self, client: QdrantClient) -> None:
        self._client = client

    def upsert_all(self, points: list[models.PointStruct]) -> int:
        """
        운동 벡터 포인트를 벡터DB에 batch upsert 합니다.

        Returns:
        - upsert된 포인트 수
        """

        if not points:
            return 0

        try:
            vector_size = len(points[0].vector)  # type: ignore[arg-type]
            self._ensure_collection(vector_size)

            self._client.upsert(
                collection_name=COLLECTION_NAME,
                points=points,
            )

            from app.data.qdrant_client import record_collection_update

            record_collection_update(COLLECTION_NAME)

            return len(points)
        except Exception as e:
            raise translate_qdrant_error(e) from e

    def search(
        self,
        query_vector: list[float],
        limit: int = 20,
        score_threshold: float = 0.5,
    ) -> list[models.ScoredPoint]:
        """
        쿼리 벡터와 유사한 운동을 검색합니다.

        Returns:
        - 유사도 순으로 정렬된 ScoredPoint 목록
        """
        try:
            response = self._client.query_points(
                collection_name=COLLECTION_NAME,
                query=query_vector,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True,
            )
            return response.points
        except Exception as e:
            raise translate_qdrant_error(e) from e

    def _ensure_collection(self, vector_size: int) -> None:
        """
        컬렉션이 없으면 생성
        upsert 시 호출되며, vector_size는 최초 upsert 시점에 추론하여 전달
        """
        try:
            existing = {c.name for c in self._client.get_collections().collections}
            if COLLECTION_NAME in existing:
                return

            self._client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,  # TODO
                ),
            )
            logger.info(
                "Qdrant 컬렉션 생성: %s (dim=%d, distance=Cosine)",  # TODO
                COLLECTION_NAME,
                vector_size,
            )

        except Exception as e:
            raise translate_qdrant_error(e) from e
