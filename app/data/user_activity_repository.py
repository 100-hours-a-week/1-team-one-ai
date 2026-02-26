# app/data/user_activity_repository.py
"""
UserActivityRepository Protocol과 QdrantUserActivityRepository 구현체를 분리
이후 컬렉션 변경이나 저장소 교체 시 구현체만 교체

UserActivityRepository (Protocol + QdrantUserActivityRepository)
upsert(user_id, vector, payload)

실제 Qdrant client.upsert() 호출 : QdrantUserActivityRepository.upsert()
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from qdrant_client import QdrantClient, models

from app.domain.user_activity import UserActivityProfile

COLLECTION_NAME = "user_activity_profiles"


# ── Protocol (추상) ──────────────────────────────────────────────────────────


@runtime_checkable
class UserActivityRepository(Protocol):
    def upsert(self, profile: UserActivityProfile, vector: list[float]) -> None:
        """사용자 활동 프로필을 벡터DB에 저장 (신규 생성 또는 갱신)"""
        ...
        # TODO: QdrantClient.upsert() 호출

    def exists(self, user_id: int) -> bool:
        """해당 user_id의 프로필이 이미 존재하는지 확인"""
        ...
        # TODO: QdrantClient.retrieve() 호출


# ── 구현체 ────────────────────────────────────────────────────────────────────


class QdrantUserActivityRepository:
    """
    UserActivityRepository의 Qdrant 구현체.

    - upsert: user_id를 Point id로 사용 → 동일 user_id 재호출 시 갱신
    - exists: retrieve로 단건 조회, 404(not found)면 False 반환
    """

    def __init__(self, client: QdrantClient) -> None:
        self._client = client

    def upsert(self, profile: UserActivityProfile, vector: list[float]) -> None:
        point = models.PointStruct(
            id=profile.user_id,
            vector=vector,
            payload=profile.to_payload(),
        )
        self._client.upsert(
            collection_name=COLLECTION_NAME,
            points=[point],
        )

    def exists(self, user_id: int) -> bool:
        results = self._client.retrieve(
            collection_name=COLLECTION_NAME,
            ids=[user_id],
            with_payload=False,
            with_vectors=False,
        )
        return len(results) > 0
