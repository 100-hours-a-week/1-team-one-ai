# app/services/user_activity/activity_service.py
"""
UserActivityService (오케스트레이터)
- build_and_upsert(user_id) → coreBE 호출 → 빌드 → upsert
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import httpx

from app.data.user_activity_repository import UserActivityRepository
from app.schemas.v2.user_activity import UserActivityApiResponse
from app.services.user_activity.profile_builder import UserActivityProfileBuilder

# ── coreBE 클라이언트 Protocol ────────────────────────────────────────────────


@runtime_checkable
class ActivityDataClient(Protocol):
    async def fetch(self, user_id: int) -> UserActivityApiResponse:
        """coreBE로부터 사용자 활동 데이터를 조회합니다."""
        ...


class HttpActivityDataClient:
    """
    ActivityDataClient의 HTTP 구현체.
    coreBE의 GET /users/{user_id}/activity-data 엔드포인트를 호출합니다.
    """

    def __init__(self, base_url: str, client: httpx.AsyncClient) -> None:
        self._base_url = base_url
        self._client = client

    async def fetch(self, user_id: int) -> UserActivityApiResponse:
        response = await self._client.get(f"{self._base_url}/users/{user_id}/activity-data")
        response.raise_for_status()
        return UserActivityApiResponse.model_validate(response.json())


# ── 임베딩 모델 Protocol ──────────────────────────────────────────────────────


@runtime_checkable
class EmbeddingModel(Protocol):
    def encode(self, text: str) -> list[float]:
        """텍스트를 벡터로 변환합니다."""
        ...
        # TODO: 임베딩 모델 호출


# ── UserActivityService ───────────────────────────────────────────────────────


class UserActivityService:
    """
    사용자 활동 프로필 생성 흐름의 오케스트레이터.

    흐름: coreBE fetch → profile build → passage 생성 → 임베딩 → upsert
    외부 의존성은 모두 Protocol로 주입받아 구현체와 분리합니다.

    DI 조립 예시 (Qdrant 연동 완료 후):
        from app.data.loader import exercise_repository
        from app.data.user_activity_repository import QdrantUserActivityRepository
        from app.data.qdrant_client import get_qdrant_client  # TODO: 구현 후 활성화

        builder = UserActivityProfileBuilder(exercises=exercise_repository.raw_data)
        repository = QdrantUserActivityRepository(client=get_qdrant_client())
        service = UserActivityService(
            data_client=HttpActivityDataClient(base_url=settings.CORE_BE_URL, client=httpx_client),
            builder=builder,
            embedding_model=...,   # TODO: SentenceTransformer 인스턴스
            repository=repository,
        )
    """

    def __init__(
        self,
        data_client: ActivityDataClient,
        builder: UserActivityProfileBuilder,
        embedding_model: EmbeddingModel,
        repository: UserActivityRepository,
    ) -> None:
        self._data_client = data_client
        self._builder = builder
        self._embedding_model = embedding_model
        self._repository = repository

    async def build_and_upsert(self, user_id: int) -> None:
        """
        1. coreBE로부터 활동 데이터 조회
        2. 활동 프로필 생성
        3. passage 생성 → 임베딩
        4. Qdrant upsert
        """
        # 1. fetch
        api_response = await self._data_client.fetch(user_id)

        # 2. build
        profile = self._builder.build(api_response)

        # 3. encode
        passage = self._builder.to_passage(profile)
        vector = self._embedding_model.encode(passage)

        # 4. upsert
        self._repository.upsert(profile, vector)

    def is_non_cold_state(self, user_id: int) -> bool:
        """
        Qdrant에 해당 user_id의 활동 프로필이 존재하면 non-cold-state로 판단합니다.
        ColdStartChecker와의 연계 지점입니다.
        """
        return self._repository.exists(user_id)
