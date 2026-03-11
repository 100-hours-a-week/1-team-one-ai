# app/data/satisfaction_repository.py
"""
사용자 운동 만족도 Sparse Vector 저장소

SatisfactionRepository (Protocol)
  - upsert(user_id, satisfactions) → None
  - search_similar_users(satisfactions, limit) → list[rest.ScoredPoint]
  - get_user_satisfaction(user_id) → dict[int, float] | None

QdrantSatisfactionRepository
  - exercise_satisfaction 컬렉션에 사용자별 sparse vector 저장
  - 운동 ID = indices, EWMA 누적 점수 (-1.0 ~ 1.0) = values
  - Dot Product 유사도 기준 (sparse vector CF 표준)

[EWMA 누적 처리]
  coreBE는 항상 최신 raw rating (+1/-1, 최신값 덮어쓰기)을 전송한다.
  AI 서버는 직전 raw rating과 비교하여 실제 변경이 있을 때만 EWMA를 적용한다.
  이를 통해 루틴 단위 만족도의 노이즈를 완화하고, 반복 배치 전송 시 spurious 업데이트를 방지한다.

  EWMA 공식: new_score = α × new_rating + (1 - α) × old_score
  - α = EWMA_ALPHA (기본값 0.3)
  - 첫 평가: EWMA 없이 raw rating 그대로 사용
  - 배치 재전송 시 동일 rating: EWMA 재적용 없이 기존 점수 유지
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from qdrant_client import QdrantClient
from qdrant_client.http import models as rest

from app.data.qdrant_exceptions import translate_qdrant_error

logger = logging.getLogger(__name__)

COLLECTION_NAME = "exercise_satisfaction"
SPARSE_VECTOR_NAME = "satisfaction"

EWMA_ALPHA = 0.3  # EWMA 학습률 (UP: 최근 반응성 증가, DOWN: 누적 안정성 증가)
# EWMA_ALPHA 변경 시 영향:
#   0.3 (기본): 최근 평가 30% 반영, 3~4번 반복 평가 후 수렴
#   0.5: 최근 평가 50% 반영, 더 빠른 수렴
#   0.1: 최근 평가 10% 반영, 느린 수렴 (과거 신호 강하게 유지)


# ── 유틸 ────────────────────────────────────────────────────────────────────


def _to_sparse_vector(scores: dict[int, float]) -> rest.SparseVector:
    """딕셔너리 형태의 점수를 Qdrant SparseVector로 변환.

    입력: {51: 0.7, 52: -0.4}
    출력: SparseVector(indices=[51, 52], values=[0.7, -0.4])
    """
    indices: list[int] = []
    values: list[float] = []
    for exercise_id, score in scores.items():
        if score != 0:
            indices.append(exercise_id)
            values.append(float(score))
    return rest.SparseVector(indices=indices, values=values)


# ── Protocol ─────────────────────────────────────────────────────────────────


@runtime_checkable
class SatisfactionRepository(Protocol):
    def upsert(self, user_id: int, satisfactions: dict[int, float]) -> None:
        """사용자의 운동 만족도 sparse vector를 upsert합니다.

        Args:
        - user_id: 사용자 ID (Qdrant point ID로 사용)
        - satisfactions: {exerciseId: raw_rating (+1.0 or -1.0)} — coreBE에서 전송한 최신 raw rating
        """
        ...

    def search_similar_users(
        self,
        satisfactions: dict[int, float],
        limit: int = 20,
    ) -> list[rest.ScoredPoint]:
        """주어진 만족도 벡터와 유사한 사용자를 검색합니다.

        Sparse vector inner product 기반 유사도로 상위 limit 명의 사용자를 반환합니다.

        Args:
        - satisfactions: 쿼리용 만족도 딕셔너리 {exerciseId: satisfaction}
        - limit: 반환할 최대 유사 사용자 수

        Returns:
        - 유사도 순으로 정렬된 ScoredPoint 목록
          payload: {"user_id": int, "exercise_ids": list[int]}
        """
        ...

    def get_user_satisfaction(self, user_id: int) -> dict[int, float] | None:
        """사용자의 만족도 데이터를 조회합니다.

        Returns:
        - {exerciseId: ewma_score} 또는 None (데이터 없음)
        """
        ...


# ── 구현체 ───────────────────────────────────────────────────────────────────


class QdrantSatisfactionRepository:
    """SatisfactionRepository의 Qdrant 구현체.

    - upsert 최초 호출 시 컬렉션 자동 생성 (존재하면 skip)
    - sparse vector 컬렉션 (dense vector 미사용)
    - 유사도 기준: Dot Product (CF sparse vector 표준)
    - sparse vector values = EWMA 누적 점수 (binary +1/-1 아님)
    """

    def __init__(self, client: QdrantClient) -> None:
        self._client = client

    def upsert(self, user_id: int, satisfactions: dict[int, float]) -> None:
        """사용자의 운동 만족도를 EWMA 누적 점수로 변환하여 upsert합니다.

        coreBE로부터 받은 raw rating (+1/-1)을 직전 raw rating과 비교하여
        변경이 있을 때만 EWMA를 적용한다. 배치 재전송 시 동일 rating이면 점수 변경 없음.

        [처리 흐름]
        1. Qdrant에서 기존 EWMA 점수 + 직전 raw rating 조회
        2. 변경된 운동만 EWMA 적용 (new_score = α × new_rating + (1-α) × old_score)
        3. 새 운동(첫 평가)은 raw rating 그대로 사용
        4. 변경이 없으면 Qdrant 업데이트 skip
        """
        try:
            self._ensure_collection()

            # 기존 상태 조회 (EWMA 점수 + 직전 raw rating)
            ewma_scores, last_raw_ratings = self._get_existing_state(user_id)

            # 변경된 운동에만 EWMA 적용
            updated = False
            for exercise_id, new_rating in satisfactions.items():
                old_rating = last_raw_ratings.get(exercise_id)
                if old_rating is None:
                    # 첫 평가: raw rating 그대로 저장
                    ewma_scores[exercise_id] = new_rating
                    last_raw_ratings[exercise_id] = new_rating
                    updated = True
                elif new_rating != old_rating:
                    # 평가 변경: EWMA 적용
                    old_score = ewma_scores.get(exercise_id, float(old_rating))
                    ewma_scores[exercise_id] = (
                        EWMA_ALPHA * new_rating + (1 - EWMA_ALPHA) * old_score
                    )
                    last_raw_ratings[exercise_id] = new_rating
                    updated = True
                # 동일 rating: EWMA 재적용 없이 기존 점수 유지

            if not updated:
                logger.debug("만족도 변경 없음 — skip [user_id=%d]", user_id)
                return

            sparse_vec = _to_sparse_vector(ewma_scores)
            point = rest.PointStruct(
                id=user_id,
                vector={SPARSE_VECTOR_NAME: sparse_vec},
                payload={
                    "user_id": user_id,
                    # score != 0인 운동만 포함 (_to_sparse_vector와 동일 기준)
                    "exercise_ids": [eid for eid, s in ewma_scores.items() if s != 0],
                    # 변경 감지용: 직전에 전송된 raw rating 기록 (EWMA 재적용 방지)
                    "last_raw_ratings": {str(k): v for k, v in last_raw_ratings.items()},
                },
            )
            self._client.upsert(collection_name=COLLECTION_NAME, points=[point])
            logger.debug(
                "만족도 upsert 완료 [user_id=%d, exercises=%d개]",
                user_id,
                len(ewma_scores),
            )
        except Exception as e:
            raise translate_qdrant_error(e) from e

    def search_similar_users(
        self,
        satisfactions: dict[int, float],
        limit: int = 20,
    ) -> list[rest.ScoredPoint]:
        """주어진 만족도 벡터와 유사한 사용자를 검색합니다."""
        try:
            sparse_vec = _to_sparse_vector(satisfactions)
            response = self._client.query_points(
                collection_name=COLLECTION_NAME,
                query=sparse_vec,
                using=SPARSE_VECTOR_NAME,
                limit=limit,
                with_payload=True,
            )
            return response.points
        except Exception as e:
            raise translate_qdrant_error(e) from e

    def get_user_satisfaction(self, user_id: int) -> dict[int, float] | None:
        """사용자의 EWMA 누적 만족도 점수를 조회합니다."""
        try:
            if not self._client.collection_exists(COLLECTION_NAME):
                return None

            results = self._client.retrieve(
                collection_name=COLLECTION_NAME,
                ids=[user_id],
                with_vectors=True,
                with_payload=False,
            )
            if not results:
                return None

            point = results[0]
            vectors = point.vector
            if not isinstance(vectors, dict) or SPARSE_VECTOR_NAME not in vectors:
                return None

            sparse = vectors[SPARSE_VECTOR_NAME]
            if not hasattr(sparse, "indices"):
                return None

            return {int(idx): float(val) for idx, val in zip(sparse.indices, sparse.values)}  # type: ignore
        except Exception as e:
            raise translate_qdrant_error(e) from e

    def _get_existing_state(
        self, user_id: int
    ) -> tuple[dict[int, float], dict[int, float]]:
        """기존 EWMA 점수와 직전 raw rating을 조회합니다.

        Returns:
        - (ewma_scores, last_raw_ratings): 없으면 빈 dict
        """
        try:
            results = self._client.retrieve(
                collection_name=COLLECTION_NAME,
                ids=[user_id],
                with_vectors=True,
                with_payload=True,
            )
        except Exception as e:
            raise translate_qdrant_error(e) from e

        if not results:
            return {}, {}

        point = results[0]

        # EWMA 점수 (sparse vector values)
        ewma_scores: dict[int, float] = {}
        vectors = point.vector
        if isinstance(vectors, dict) and SPARSE_VECTOR_NAME in vectors:
            sparse = vectors[SPARSE_VECTOR_NAME]
            if hasattr(sparse, "indices"):
                ewma_scores = {
                    int(idx): float(val)
                    for idx, val in zip(sparse.indices, sparse.values)  # type: ignore
                }

        # 직전 raw rating (payload)
        last_raw_ratings: dict[int, float] = {}
        if point.payload:
            raw = point.payload.get("last_raw_ratings", {})
            last_raw_ratings = {int(k): float(v) for k, v in raw.items()}

        return ewma_scores, last_raw_ratings

    def _ensure_collection(self) -> None:
        """컬렉션이 없으면 생성."""
        try:
            existing = {c.name for c in self._client.get_collections().collections}
            if COLLECTION_NAME in existing:
                return

            self._client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config={},  # dense vector 미사용
                sparse_vectors_config={SPARSE_VECTOR_NAME: rest.SparseVectorParams()},
            )
            logger.info("Qdrant 컬렉션 생성: %s (sparse, Dot Product)", COLLECTION_NAME)
        except Exception as e:
            raise translate_qdrant_error(e) from e
