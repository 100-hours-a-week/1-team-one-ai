# app/data/user_activity_repository.py
"""
UserActivityRepository Protocol과 QdrantUserActivityRepository 구현체.

upsert(user_id, vector, payload) — 신규 생성 또는 갱신
exists(user_id)                  — cold start 판단용

TODO: ActivityBasedColdStartChecker 활성화 시 app/api/v2/recommend.py 의
      _cold_start_checker 를 DefaultColdStartChecker → ActivityBasedColdStartChecker 로 교체
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from qdrant_client import QdrantClient, models

logger = logging.getLogger(__name__)

COLLECTION_NAME = "user_activity_profiles"


# ── Protocol (추상) ──────────────────────────────────────────────────────────


@runtime_checkable
class UserActivityRepository(Protocol):
    def upsert(self, user_id: int, vector: list[float], payload: dict) -> None:
        """사용자 활동 프로필을 벡터DB에 저장 (신규 생성 또는 갱신)"""
        ...

    def exists(self, user_id: int) -> bool:
        """해당 user_id의 프로필이 이미 존재하는지 확인"""
        ...


# ── 구현체 ────────────────────────────────────────────────────────────────────


class QdrantUserActivityRepository:
    """
    UserActivityRepository의 Qdrant 구현체.

    - upsert: user_id를 Point id로 사용 → 동일 user_id 재호출 시 갱신
    - exists: retrieve로 단건 조회, 결과 없으면 False 반환
    - 컬렉션 미존재 시 upsert 최초 호출에서 자동 생성
    """

    def __init__(self, client: QdrantClient) -> None:
        self._client = client

    def upsert(self, user_id: int, vector: list[float], payload: dict) -> None:
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

    def exists(self, user_id: int) -> bool:
        # TODO: 컬렉션이 없을 때 qdrant_client.exceptions.UnexpectedResponse 발생 가능
        #       cold start checker 활성화 전 _ensure_collection 선행 필요 여부 검토
        results = self._client.retrieve(
            collection_name=COLLECTION_NAME,
            ids=[user_id],
            with_payload=False,
            with_vectors=False,
        )
        return len(results) > 0

    def _ensure_collection(self, vector_size: int) -> None:
        """컬렉션이 없으면 생성합니다."""
        existing = {c.name for c in self._client.get_collections().collections}
        if COLLECTION_NAME in existing:
            return

        self._client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            ),
        )
        logger.info(
            "Qdrant 컬렉션 생성: %s (dim=%d, distance=Cosine)",
            COLLECTION_NAME,
            vector_size,
        )
