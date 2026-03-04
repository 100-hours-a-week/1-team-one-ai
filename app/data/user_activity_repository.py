# app/data/user_activity_repository.py
"""
사용자 활동 프로필 벡터 저장소

UserActivityVectorRepository (Protocol)
  - upsert(user_id, vector, payload) → None
  - exists(user_id) → bool

QdrantUserActivityVectorRepository
  - 컬렉션이 없으면 자동 생성 (벡터 차원은 upsert 시 추론)
  - Cosine 유사도 기준 #TODO: 향후 거리 기준을 컬렉션 단위로 유연하게 설정할 수 있도록 개선 가능
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from qdrant_client import QdrantClient, models

from app.data.qdrant_exceptions import translate_qdrant_error

logger = logging.getLogger(__name__)


COLLECTION_NAME = "user_activity_profiles"
# TODO: Constants 중앙 집중 관리 - app/core/constants.py 등 별도 모듈로 이동 검토


# ── Protocol ───────────────────────────────────────────────────────────


@runtime_checkable
class UserActivityVectorRepository(Protocol):
    def upsert(self, user_id: int, vector: list[float], payload: dict) -> None:
        """사용자 활동 프로필을 벡터DB에 저장 (신규 생성 또는 갱신)"""
        ...

    def exists(self, user_id: int) -> bool:
        """해당 user_id의 프로필이 이미 존재하는지 확인"""
        ...


# ── Interface ──────────────────────────────────────────────────────────


class QdrantUserActivityVectorRepository:
    """
    UserActivityVectorRepository의 Qdrant 구현체.

    - upsert: user_id를 Point id로 사용 → 동일 user_id 재호출 시 갱신
    - exists: retrieve로 단건 조회, 결과 없으면 False 반환
    - 컬렉션 미존재 시 upsert 최초 호출에서 자동 생성
    - 거리 기준: Cosine (시맨틱 유사도)
    # TODO: 거리 기준을 컬렉션 단위로 유연하게 설정할 수 있도록 개선 가능

    """

    def __init__(self, client: QdrantClient) -> None:
        self._client = client

    def upsert(self, user_id: int, vector: list[float], payload: dict) -> None:
        """사용자 활동 프로필을 벡터DB에 저장 (신규 생성 또는 갱신)"""

        if not vector:
            return

        try:
            self._ensure_collection(len(vector))
            point = models.PointStruct(
                id=user_id,
                vector=vector,
                payload=payload,
            )
            self._client.upsert(
                collection_name=COLLECTION_NAME,
                points=[point],
            )

            from app.data.qdrant_client import record_collection_update

            record_collection_update(COLLECTION_NAME)

        except Exception as e:
            raise translate_qdrant_error(e) from e

    def exists(self, user_id: int) -> bool:
        """
        해당 user_id의 프로필이 이미 존재하는지 확인
        ActivityBasedColdStartChecker.is_cold_start에서 사용
        """
        try:
            # 컬렉션 자체가 없으면 유저도 없음 → False
            if not self._client.collection_exists(COLLECTION_NAME):
                return False

            results = self._client.retrieve(
                collection_name=COLLECTION_NAME,
                ids=[user_id],
                with_payload=False,
                with_vectors=False,
            )
            return len(results) > 0

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
