# app/services/cold_start_checker.py
"""
Cold Start 여부 판단 인터페이스 및 구현체
- class ColdStartChecker(Protocol)        — cold start 판단 인터페이스
- class DefaultColdStartChecker           — 항상 cold start로 판단 (MVP)
- class ActivityBasedColdStartChecker     — Qdrant 프로필 존재 여부 기반 판단 (TODO)

[교체 방법]
1. ColdStartChecker Protocol을 만족하는 구현체를 선택
2. app/api/v2/recommend.py 의 _cold_start_checker 인스턴스만 교체
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.services.user_activity.activity_service import UserActivityService

logger = logging.getLogger(__name__)


class ColdStartChecker(Protocol):
    """
    사용자의 cold start 여부를 판단하는 인터페이스

    Returns:
    - True : cold start  → 설문 기반 rule 추천 사용
    - False: non-cold    → 벡터 기반 개인화 추천 사용 (TODO)
    """

    def is_cold_start(self, user_id: int) -> bool: ...


class DefaultColdStartChecker:
    """
    MVP 구현체: 항상 cold start로 판단.
    모든 사용자를 cold start로 처리 → 설문 기반 추천 사용.
    """

    def is_cold_start(self, user_id: int) -> bool:
        logger.debug("Cold start 판단 [user_id=%d]: True (기본값)", user_id)
        return True


class ActivityBasedColdStartChecker:
    """
    Qdrant 사용자 활동 프로필 존재 여부 기반 cold start 판단.

    UserActivityService.is_non_cold_state()를 위임하여 판단합니다.
    - Qdrant에 해당 user_id의 프로필이 존재 → non-cold (False)
    - 존재하지 않음                          → cold start (True)

    교체 시점:
    - Qdrant 연동 및 UserActivityRepository 구현 완료 후
    - app/api/v2/recommend.py 의 _cold_start_checker 를 이 구현체로 교체

    TODO: Qdrant 연동 완료 후 DefaultColdStartChecker 대신 이 구현체 사용
    """

    def __init__(self, activity_service: UserActivityService) -> None:
        self._activity_service = activity_service

    def is_cold_start(self, user_id: int) -> bool:
        is_non_cold = self._activity_service.is_non_cold_state(user_id)
        logger.debug(
            "Cold start 판단 [user_id=%d]: %s (활동 프로필 기반)",
            user_id,
            not is_non_cold,
        )
        return not is_non_cold
