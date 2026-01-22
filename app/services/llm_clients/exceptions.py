# app/services/llm_clients/exceptions.py

__all__ = [
    "LLMError",
    "LLMTimeoutError",
    "LLMNetworkError",
    "LLMInvalidResponseError",
    "LLMAuthenticationError",
]


class LLMError(Exception):
    """LLM 클라이언트 공통 베이스 예외"""


class LLMTimeoutError(LLMError):
    """LLM 호출 타임아웃"""


class LLMNetworkError(LLMError):
    """네트워크 오류 / 연결 실패 (Internal Server Error 포함)"""


class LLMInvalidResponseError(LLMError):
    """응답 형식이 기대와 다를 때"""


class LLMAuthenticationError(LLMError):
    """인증 실패 / 잘못된 API 키"""
