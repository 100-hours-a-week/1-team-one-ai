# app/data/exercise_vector_repository.py
"""
운동 벡터 저장소

ExerciseVectorRepository (Protocol)
  - upsert_all(points) → int

QdrantExerciseVectorRepository
  - Qdrant exercises 컬렉션에 벡터 batch upsert

TODO: Qdrant 연동 시 컬렉션 초기화 로직 추가
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from qdrant_client import QdrantClient, models

COLLECTION_NAME = "exercises"


# ── Protocol (추상) ───────────────────────────────────────────────────────────


@runtime_checkable
class ExerciseVectorRepository(Protocol):
    def upsert_all(self, points: list[models.PointStruct]) -> int:
        """운동 벡터 포인트를 벡터DB에 batch upsert 합니다.

        Returns:
            upsert된 포인트 수
        """
        ...


# ── 구현체 ────────────────────────────────────────────────────────────────────


class QdrantExerciseVectorRepository:
    """
    ExerciseVectorRepository의 Qdrant 구현체.

    - upsert_all: exerciseId(int)를 Point id로 사용 → 동일 id 재호출 시 갱신
    - 컬렉션은 Qdrant에 미리 생성되어 있다고 가정
      (TODO: Qdrant 연동 시 create_collection 로직 추가)
    """

    def __init__(self, client: QdrantClient) -> None:
        self._client = client

    def upsert_all(self, points: list[models.PointStruct]) -> int:
        if not points:
            return 0
        self._client.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
        )
        return len(points)
