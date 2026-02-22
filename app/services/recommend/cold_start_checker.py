# app/services/cold_start_checker.py
"""
Cold Start 여부 판단 인터페이스 및 기본 구현
- class ColdStartChecker(Protocol) — cold start 판단 인터페이스
- class DefaultColdStartChecker    — 항상 cold start로 판단 (MVP)

[교체 방법]
1. ColdStartChecker Protocol을 만족하는 새 구현체를 이 파일에 추가
2. recommend.py의 get_cold_start_checker()에서 반환 타입만 변경
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class ColdStartChecker(Protocol):
    """
    사용자의 cold start 여부를 판단하는 인터페이스
    - 향후 사용자 프로필/추천 이력 존재 여부로 판단
    - 현재는 항상 True (cold start) 반환

    교체 시점:
    - 사용자 프로필/추천 이력 저장소 구현 후
    - recommend.py의 get_cold_start_checker()에서 구현체만 변경
    """

    def is_cold_start(self, user_id: int) -> bool:
        """
        사용자가 cold start 상태인지 판단

        Args:
        - user_id: 사용자 식별자

        Returns:
        - True: cold start (설문 기반 rule 추천 사용)
        - False: non-cold start (벡터 기반 개인화 추천 사용)
        """
        ...


class DefaultColdStartChecker:
    """
    MVP 구현체: 항상 cold start로 판단
    - 모든 사용자를 cold start로 처리 → 설문 기반 추천 사용
    - 향후 사용자 프로필 DB/벡터 스토어 조회 구현체로 교체
    """

    def is_cold_start(self, user_id: int) -> bool:
        logger.debug(
            "Cold start 판단 [user_id=%d]: True (기본값)",
            user_id,
        )
        # TODO: 실제 cold start 판별 로직 추가
        return True
