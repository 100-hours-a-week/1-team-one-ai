# app/services/user_activity/profile_service.py
"""
사용자 활동 프로필 벡터 upsert 서비스.

UserActivityProfileService
  - try_upsert_batch(profiles) → int
    - passage 생성 → 임베딩 → repository.upsert()
    - Qdrant 미연결 / embedding_model 미설정 시 조용히 건너뜀 (silent skip)
    - 예외 발생 시 WARNING 로그 후 흐름 유지
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.data.user_activity_repository import UserActivityRepository

from app.schemas.v2.user_activity import UserProfile

logger = logging.getLogger(__name__)

MIN_RATIO = 0.1  # passage 생성 시 포함할 최소 비율 임계값


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


# ── UserActivityProfileService ────────────────────────────────────────────────


class UserActivityProfileService:
    """
    사용자 활동 프로필 → Qdrant 벡터 upsert 오케스트레이터.

    - embedding_model 또는 repository 가 None 이면 debug 로그 후 건너뜀
    - upsert 도중 예외 발생 시 WARNING 로그 후 건너뜀 (기존 API 흐름 영향 없음)
    """

    def __init__(
        self,
        repository: UserActivityRepository | None,
        embedding_model: Any | None,  # SentenceTransformer 등 encode() 지원 모델
    ) -> None:
        self._repository = repository
        self._embedding_model = embedding_model

    def try_upsert_batch(self, profiles: list[UserProfile]) -> int:
        """
        사용자 프로필 목록을 벡터DB에 upsert 합니다.

        - Qdrant 미연결 / 모델 미설정 시: DEBUG 로그 후 0 반환
        - 실행 중 예외 발생 시: WARNING 로그 후 0 반환
        """
        if self._repository is None or self._embedding_model is None:
            logger.debug(
                "UserActivityProfileService: repository=%s, embedding_model=%s — 벡터 upsert 건너뜀",
                "설정됨" if self._repository else "미설정",
                "설정됨" if self._embedding_model else "미설정",
            )
            return 0

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
            return len(profiles)

        except Exception as e:
            logger.warning(
                "user activity 벡터 upsert 실패 (Qdrant 미연결 또는 오류): %s",
                e,
                exc_info=False,
            )
            return 0
