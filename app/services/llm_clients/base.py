# app/services/llm_clients/base.py

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel

from app.core.exceptions import ExpectedServiceError


class LLMClient(ABC):
    """
    공통 LLM 호출 인터페이스

    - prompt 포맷 가공 X
    - 응답 파싱 X
    - provider-specific 옵션 X
    """

    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        response_schema: type[BaseModel] | None = None,
        timeout: Optional[float] = None,
    ) -> str:
        """
        LLM에 system_prompt와 user_prompt를 전달하고 원시 텍스트 응답을 반환한다.

        Args:
            system_prompt: 시스템 역할이나 전역 지침을 담은 프롬프트
            user_prompt: 사용자 입력 프롬프트
            response_schema: 선택적 pydantic 모델 타입. 응답을 구조화할 때 사용(구현체별 처리 상이)
            timeout: 요청 타임아웃(초). None이면 기본값 사용

        Returns:
            LLM이 생성한 원시 텍스트 응답

        Raises:
            LLMTimeoutError: 요청 타임아웃
            LLMNetworkError: 네트워크/연결 오류
            LLMInvalidResponseError: 예상치 못한 응답 형식
        """
        ...


class LLMError(ExpectedServiceError):  # Reparent from Exception
    """LLM 클라이언트 공통 베이스 예외"""


class LLMTimeoutError(LLMError):
    """LLM 호출 타임아웃"""


class LLMNetworkError(LLMError):
    """네트워크 오류 / 연결 실패 (Internal Server Error 포함)"""


class LLMInvalidResponseError(LLMError):
    """응답 형식이 기대와 다를 때"""


class LLMAuthenticationError(LLMError):
    """인증 실패 / 잘못된 API 키"""
