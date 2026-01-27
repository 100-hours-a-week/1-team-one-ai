"""
app/services/llm_clients/ollama_client.py
"""

from __future__ import annotations

from typing import Optional

from httpx import TimeoutException
from ollama import Client, RequestError, ResponseError
from pydantic import BaseModel

from app.services.llm_clients.base import (
    LLMAuthenticationError,
    LLMClient,
    LLMInvalidResponseError,
    LLMNetworkError,
    LLMTimeoutError,
)


class OllamaClient(LLMClient):
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-oss:120b-cloud",
        default_timeout: float = 30.0,
    ) -> None:
        self._client = Client(
            host="https://ollama.com",  # "http://localhost:11434"
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=default_timeout,
        )
        self._model = model
        self._default_timeout = default_timeout

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        response_schema: type[BaseModel] | None = None,
        timeout: Optional[float] = None,
    ) -> str:
        """
        Ollama Cloud API를 호출하여 텍스트를 생성한다.

        Args:
            system_prompt: 시스템 레벨 지침 프롬프트.
            user_prompt: 사용자 프롬프트 문자열.
            response_schema: Optional Pydantic 모델 타입
            timeout: 요청 타임아웃(초). Ollama Python SDK는 per-request timeout을 적용하지 않을 수 있으므로
                 기본 timeout(self._default_timeout)이 사용됩니다.

        Returns:
            생성된 응답 텍스트 (앞뒤 공백 제거됨).

        Raises:
            LLMTimeoutError: 요청 타임아웃 발생 시.
            LLMNetworkError: 네트워크 오류, 서버 오류, rate limit 등.
            LLMAuthenticationError: API 키 인증 실패 시 (401).
            LLMInvalidResponseError: 모델 없음(404) 또는 응답 형식 오류.
        """
        request_timeout = timeout or self._default_timeout
        _ = request_timeout  # timeout is handled at client init

        try:
            parse_kwargs: dict = {}
            if response_schema is not None:
                parse_kwargs["format"] = response_schema.model_json_schema()

            response = self._client.generate(
                model=self._model,
                system=system_prompt,
                prompt=user_prompt,
                **parse_kwargs,
            )

        except TimeoutException as exc:
            raise LLMTimeoutError("Ollama request timed out") from exc

        except ResponseError as exc:
            self._handle_response_error(exc)

        except RequestError as exc:
            raise LLMNetworkError(f"Ollama request error: {exc}") from exc

        try:
            content = response.response
            if not isinstance(content, str):
                raise LLMInvalidResponseError(
                    "Ollama returned unexpected response format: content is not a string"
                )

            return content.strip()

        except AttributeError as exc:
            raise LLMInvalidResponseError("Ollama returned unexpected response format") from exc

    def _handle_response_error(self, exc: ResponseError) -> None:
        """ResponseError를 status_code에 따라 적절한 LLM 예외로 변환한다."""
        status = exc.status_code
        error_msg = str(exc.error)

        if status == 400:
            raise LLMInvalidResponseError(f"Ollama bad request: {error_msg}") from exc

        if status == 401:
            raise LLMAuthenticationError(f"Ollama authentication failed: {error_msg}") from exc

        if status == 404:
            raise LLMInvalidResponseError(f"Ollama model not found: {error_msg}") from exc

        if status == 429:
            raise LLMNetworkError(f"Ollama rate limit exceeded: {error_msg}") from exc

        if status == 500:
            raise LLMNetworkError(f"Ollama internal server error: {error_msg}") from exc

        if status == 502:
            raise LLMNetworkError(
                f"Ollama bad gateway (cloud model unreachable): {error_msg}"
            ) from exc

        raise LLMNetworkError(f"Ollama error (status {status}): {error_msg}") from exc
