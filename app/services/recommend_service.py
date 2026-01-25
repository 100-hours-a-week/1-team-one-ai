# app/services/recommend_service.py

"""
운동 루틴 추천 서비스
- LLM 기반 추천 (재시도 포함)
- 실패 시 룰 기반 fallback
"""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from app.configs.llm_config import llm_config
from app.core.exceptions import ConfigurationError, RoutineValidationError
from app.data.loader import exercise_repository
from app.prompts.v1.recommend import SYSTEM_PROMPT, build_user_prompt
from app.schemas.v1.request import UserSurvey
from app.schemas.v1.response import LLMRoutineOutput
from app.services.llm_clients.base import (
    LLMClient,
    LLMError,
    LLMInvalidResponseError,
    LLMNetworkError,
    LLMTimeoutError,
)
from app.services.rule_based_recommender import RuleBasedRecommender

logger = logging.getLogger(__name__)

# 재시도 대상 예외
RETRYABLE_ERRORS = (LLMTimeoutError, LLMNetworkError, LLMInvalidResponseError)


class RecommendService:
    """
    운동 루틴 추천 서비스

    동작 흐름:
    1. LLM 호출 (설정된 retry 횟수만큼 재시도)
    2. 모든 재시도 실패 시 rule-based fallback
    """

    def __init__(self, llm_client: LLMClient, exercises: list[dict] | None = None) -> None:
        """
        Args:
        - llm_client: LLM 클라이언트 인스턴스
        - exercises: 운동 데이터 리스트
        """
        self._llm = llm_client
        self._exercises = exercises if exercises is not None else exercise_repository.raw_data

        # config에서 기본값 로드
        try:
            provider_name = llm_config.default_provider
            provider_config = llm_config.providers.get(provider_name)

            if provider_config is None:
                raise ConfigurationError(f"LLM 프로바이더 '{provider_name}'가 설정에 없습니다.")

            self._max_retries = provider_config.retry
            self._fallback_enabled = llm_config.fallback

        except (KeyError, AttributeError) as e:
            raise ConfigurationError(f"LLM 설정 접근 오류: {e}") from e

        # rule-based recommender (lazy init 일단은 보류)
        if self._fallback_enabled:
            try:
                self._rule_based = RuleBasedRecommender(self._exercises)

            except ValidationError as e:
                raise RoutineValidationError(
                    f"운동 데이터 검증 실패 (fallback 초기화 불가): {e}"
                ) from e
        else:
            self._rule_based = None

    def recommend_routines(self, survey: UserSurvey) -> LLMRoutineOutput:
        """
        설문 데이터를 기반으로 운동 루틴 추천.

        Args:
        - survey: 사용자 설문 데이터

        Returns:
        - LLMRoutineOutput: 추천된 루틴 목록

        Raises:
        - LLMError: LLM 호출 실패 (fallback 비활성화 시)
        """
        user_prompt = self._build_prompt(survey)
        last_error: Exception | None = None

        # LLM 호출 (재시도 포함)
        for attempt in range(self._max_retries + 1):
            try:
                raw_response = self._llm.generate(SYSTEM_PROMPT, user_prompt)
                result = self._parse_response(raw_response)  # raise error
                logger.info("LLM 추천 성공 (시도 %d/%d)", attempt + 1, self._max_retries + 1)
                return result

            except RETRYABLE_ERRORS as e:  # 재시도 가능한 에러 (LLMTimeoutError, LLMNetworkError, LLMInvalidResponseError)
                last_error = e
                logger.warning(
                    "LLM 호출 실패 (시도 %d/%d): %s",
                    attempt + 1,
                    self._max_retries + 1,
                    e,
                )
                continue

            except LLMError as e:  # 재시도 불가능한 에러 (인증 실패 등)
                last_error = e
                logger.error("LLM 호출 실패 (재시도 불가): %s", e)
                break

        # 모든 재시도 실패 → fallback
        logger.warning(
            "LLM 모든 재시도 실패 (%d회), fallback_enabled=%s",
            self._max_retries + 1,
            self._fallback_enabled,
        )

        # fallback 활성화 시 rule-based recommender 사용하여 결과 반환
        if self._fallback_enabled and self._rule_based:
            logger.info("Rule-based fallback 실행")
            return self._rule_based.recommend_routines(survey)

        # fallback 비활성화 시 에러 전파
        raise LLMInvalidResponseError(
            f"LLM 추천 실패 (재시도 {self._max_retries + 1}회): {last_error}"
        ) from last_error

    def _build_prompt(self, survey: UserSurvey) -> str:
        """사용자 프롬프트 생성."""
        return build_user_prompt(
            user=survey,
            exercises_text=json.dumps(
                self._exercises, ensure_ascii=False
            ),  # exercise_repository.raw_data
        )

    def _parse_response(self, raw: str) -> LLMRoutineOutput:
        """LLM 응답 파싱 및 검증."""
        try:
            data = json.loads(raw)
            return LLMRoutineOutput.model_validate(data)

        except json.JSONDecodeError as e:
            logger.error("JSON 파싱 실패: %s", e)
            raise LLMInvalidResponseError(f"JSON 파싱 실패: {e}") from e

        except ValidationError as e:
            logger.error("스키마 검증 실패: %s", e)
            raise LLMInvalidResponseError(f"스키마 검증 실패: {e}") from e
