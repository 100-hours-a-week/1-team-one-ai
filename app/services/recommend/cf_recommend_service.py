# app/services/recommend/cf_recommend_service.py
"""
협업 필터링(Collaborative Filtering) + 벡터 검색 혼합 추천 서비스

CFRecommendService (VectorRecommendService 상속)
  - recommend_routines(survey, user_id) → RoutineList

[알고리즘]
  1. 설문 → 쿼리 벡터 생성 (+ 활동 벡터 블렌딩, non-cold start 시)
  2. 운동 벡터 검색 → 운동별 코사인 유사도 점수
  3. 사용자 만족도 sparse vector 조회
  4. 유사 사용자 검색 (Dot Product) → 운동별 CF 점수 집계
  5. 벡터 점수 + CF 점수 정규화 후 가중합 → 최종 순위
  6. RoutineList 변환 (VectorRecommendService._build_routine_list 재사용)

[Graceful Degradation]
  만족도 데이터 없음  → 벡터 검색만으로 fallback
  유사 사용자 없음   → 벡터 검색만으로 fallback
  CF 검색 실패      → 벡터 검색만으로 fallback + WARNING 로그
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from app.core.exceptions import ConfigurationError
from app.services.recommend.vector_recommend_service import (
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_SEARCH_LIMIT,
    VectorRecommendService,
)

if TYPE_CHECKING:
    from app.data.exercise_vector_repository import ExerciseVectorRepository
    from app.data.satisfaction_repository import SatisfactionRepository
    from app.data.user_activity_repository import UserActivityVectorRepository
    from app.domain.routine import RoutineList
    from app.schemas.common import UserSurvey
    from app.services.llm_clients.base import LLMClient

logger = logging.getLogger(__name__)

# ── 상수 ──────────────────────────────────────────────────────────────────────

CF_SIMILAR_USERS_LIMIT = 20  # 유사 사용자 검색 상한
CF_WEIGHT = 0.3  # CF 점수 가중치   (UP: CF 반영 비율 증가, DOWN: 벡터 반영 비율 증가)
VECTOR_WEIGHT = 0.5  # 벡터 점수 가중치 (= 1 - CF_WEIGHT)


# ── _ExerciseRef ──────────────────────────────────────────────────────────────


class _ExerciseRef:
    """_build_routine_list() 호환용 운동 ID 래퍼.

    ScoredPoint.id 접근 패턴(int(hit.id))을 그대로 지원하며,
    CF 블렌딩 후 재정렬된 운동 ID 목록을 VectorRecommendService의
    루틴 빌딩 로직에 전달하기 위해 사용한다.
    """

    __slots__ = ("id",)

    def __init__(self, exercise_id: int) -> None:
        self.id = exercise_id


# ── CFRecommendService ────────────────────────────────────────────────────────


class CFRecommendService(VectorRecommendService):
    """협업 필터링 + 벡터 검색 혼합 추천 서비스.

    VectorRecommendService를 상속받아 다음 메서드를 재사용한다:
      - _build_query(survey) → 설문 → 쿼리 문자열
      - _get_query_vector(survey_vector, user_id) → 활동 벡터 블렌딩
      - _build_routine_list(hits, routine_count, survey) → RoutineList 변환
      - generate_reasons(routines, survey) → LLM reason 생성

    CF 레이어 (신규):
      - _get_user_satisfaction(user_id) → 사용자 만족도 조회
      - _compute_cf_scores(satisfactions, user_id) → 유사 사용자 기반 점수 집계
      - _blend_and_rank(vector_scores, cf_scores) → 최종 순위 계산
    """

    def __init__(
        self,
        satisfaction_repo: SatisfactionRepository | None,
        exercise_repo: ExerciseVectorRepository | None,
        embedding_model: Any | None,
        llm_client: LLMClient | None = None,
        user_activity_repo: UserActivityVectorRepository | None = None,
    ) -> None:
        super().__init__(exercise_repo, embedding_model, llm_client, user_activity_repo)
        self._satisfaction_repo = satisfaction_repo

    def recommend_routines(self, survey: UserSurvey, user_id: int) -> RoutineList:
        """CF + 벡터 검색 혼합 추천.

        Args:
        - survey: 사용자 설문 데이터
        - user_id: 사용자 식별자

        Returns:
        - RoutineList (V2ResponseBuilder.build()로 이후 검증됨)

        Raises:
        - ConfigurationError: Qdrant 미연결 또는 임베딩 모델 미설정 시
        """
        if self._repo is None or self._model is None:
            raise ConfigurationError(
                "CFRecommendService 비활성화 상태입니다. "
                "Qdrant 연결 및 임베딩 모델 설정을 확인하세요."
            )

        # 1. 설문 → 쿼리 벡터 (+ 활동 벡터 블렌딩)
        query = self._build_query(survey)
        logger.debug("CF 추천 쿼리 [user_id=%d]: %s", user_id, query)

        survey_vector: list[float] = self._model.encode(query).tolist()
        query_vector = self._get_query_vector(survey_vector, user_id)

        # 2. 운동 벡터 검색
        qdrant_filter = self._build_qdrant_filter(survey)
        hits = self._repo.search(
            query_vector=query_vector,
            limit=DEFAULT_SEARCH_LIMIT,
            score_threshold=DEFAULT_SCORE_THRESHOLD,
            query_filter=qdrant_filter,
        )
        logger.info("벡터 검색 완료 [user_id=%d]: %d 개 후보", user_id, len(hits))

        # 3. 사용자 만족도 조회
        user_satisfactions = self._get_user_satisfaction(user_id)
        if not user_satisfactions:
            logger.info("만족도 데이터 없음 — 유사도 검색 결과로 완료 [user_id=%d]", user_id)
            return self._build_routine_list(hits, survey.routineCount, survey)

        # 4. 유사 사용자 기반 CF 점수 집계
        cf_scores = self._compute_cf_scores(user_satisfactions, user_id)
        if not cf_scores:
            logger.info("유사 사용자 없음 — 유사도 검색 결과로 완료 [user_id=%d]", user_id)
            return self._build_routine_list(hits, survey.routineCount, survey)

        # 5. 벡터 점수 + CF 점수 블렌딩 → 최종 순위
        vector_scores = {int(h.id): h.score for h in hits}
        ranked_ids = self._blend_and_rank(vector_scores, cf_scores)
        logger.info(
            "CF 혼합 추천 완료 [user_id=%d]: 벡터 후보 %d개, 최종 순위 %d개",
            user_id,
            len(hits),
            len(ranked_ids),
        )

        # 6. RoutineList 변환 (_build_routine_list은 hit.id만 사용)
        blended_hits = [_ExerciseRef(eid) for eid in ranked_ids]
        return self._build_routine_list(blended_hits, survey.routineCount, survey)

    # ── private ───────────────────────────────────────────────────────────────

    def _get_user_satisfaction(self, user_id: int) -> dict[int, float] | None:
        """사용자의 만족도 데이터 조회. 없거나 실패 시 None."""
        if self._satisfaction_repo is None:
            return None

        try:
            return self._satisfaction_repo.get_user_satisfaction(user_id)
        except Exception as e:
            logger.warning("만족도 조회 실패 [user_id=%d]: %s", user_id, e)
            return None

    def _compute_cf_scores(
        self, user_satisfactions: dict[int, float], user_id: int
    ) -> dict[int, float]:
        """유사 사용자 검색 → 운동별 CF 점수 집계.

        각 유사 사용자의 운동 목록에 유사도 점수를 가중합하여 CF 점수를 계산한다.
        자기 자신은 항상 가장 높은 유사도로 반환되므로 필터링한다.

        예) 유저A(score=0.9): [운동1, 운동2] → 운동1 += 0.9, 운동2 += 0.9
            유저B(score=0.7): [운동1, 운동3] → 운동1 += 0.7, 운동3 += 0.7
            결과: {운동1: 1.6, 운동2: 0.9, 운동3: 0.7}
        """
        if self._satisfaction_repo is None:
            return {}

        try:
            similar_users = self._satisfaction_repo.search_similar_users(
                user_satisfactions, limit=CF_SIMILAR_USERS_LIMIT
            )
        except Exception as e:
            logger.warning("유사 사용자 검색 실패 [user_id=%d]: %s", user_id, e)
            return {}

        exercise_scores: dict[int, float] = defaultdict(float)
        for result in similar_users:
            if result.payload is None:
                continue
            if result.payload.get("user_id") == user_id:
                # 자기 자신은 항상 dot product 최고점 → 필터링하지 않으면
                # 본인 운동이 CF 점수 상위를 독점하여 추천 다양성 저하
                continue
            for exercise_id in result.payload.get("exercise_ids", []):
                exercise_scores[int(exercise_id)] += result.score

        logger.debug(
            "CF 점수 집계 [user_id=%d]: 유사 사용자 %d명, 운동 %d개",
            user_id,
            len(similar_users),
            len(exercise_scores),
        )
        return dict(exercise_scores)

    def _blend_and_rank(
        self,
        vector_scores: dict[int, float],
        cf_scores: dict[int, float],
    ) -> list[int]:
        """벡터 점수와 CF 점수를 정규화 후 가중합하여 최종 운동 순위 반환.

        정규화: 각 점수를 최댓값으로 나눠 [0, 1] 범위로 통일.
                두 점수 공간이 다르므로(코사인 유사도 vs 유사도 누적합) 정규화 필수.
        가중합: VECTOR_WEIGHT * norm_vector + CF_WEIGHT * norm_cf
        """
        max_vector = max(vector_scores.values(), default=1.0) or 1.0
        max_cf = max(cf_scores.values(), default=1.0) or 1.0

        all_exercise_ids = set(vector_scores) | set(cf_scores)
        final_scores: dict[int, float] = {
            eid: (
                VECTOR_WEIGHT * vector_scores.get(eid, 0.0) / max_vector
                + CF_WEIGHT * cf_scores.get(eid, 0.0) / max_cf
            )
            for eid in all_exercise_ids
        }

        return sorted(final_scores, key=lambda eid: final_scores[eid], reverse=True)
