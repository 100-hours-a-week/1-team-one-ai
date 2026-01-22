# app/services/llm_clients/base.py

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

__all__ = ["LLMClient"]


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
        timeout: Optional[float] = None,
    ) -> str:
        """
        LLM에 prompt를 전달하고 raw text 응답을 반환한다.

        Args:
            prompt: LLM에 전달할 원본 프롬프트
            timeout: 요청 타임아웃 (초). None이면 기본값 사용

        Returns:
            LLM이 생성한 텍스트 응답

        Raises:
            LLMTimeoutError: 요청 타임아웃
            LLMNetworkError: 네트워크 / 연결 오류
            LLMInvalidResponseError: 예상치 못한 응답 형식
        """
        ...
