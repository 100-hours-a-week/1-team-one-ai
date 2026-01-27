# app/services/llm_clients/openai_client.py

from __future__ import annotations

from typing import Optional

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
from pydantic import BaseModel

from app.services.llm_clients.base import (
    LLMAuthenticationError,
    LLMClient,
    LLMInvalidResponseError,
    LLMNetworkError,
    LLMTimeoutError,
)


class OpenAIClient(LLMClient):
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4.1-mini",
        default_timeout: float = 30.0,
    ) -> None:
        self._client = OpenAI(api_key=api_key)
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
        """OpenAI Chat Completions API를 호출하여 텍스트를 생성한다.

        Args:
            system_prompt: 시스템 레벨 지침 프롬프트.
            user_prompt: 사용자 프롬프트 문자열.
            response_schema: Optional Pydantic 모델 타입. Structured Outputs 사용 시 적용.
            timeout: 요청 타임아웃(초). None이면 default_timeout 사용.

        Returns:
            생성된 응답 텍스트 (앞뒤 공백 제거됨).

        Raises:
            LLMTimeoutError: 요청 타임아웃 발생 시.
            LLMNetworkError: 네트워크 오류 또는 서버 오류 발생 시.
            LLMAuthenticationError: API 키 인증 실패 시.
            LLMInvalidResponseError: 응답 형식이 예상과 다를 때.
        """
        request_timeout = timeout or self._default_timeout

        try:
            parse_kwargs: dict = {}
            if response_schema is not None:
                parse_kwargs["text_format"] = response_schema

            response = self._client.responses.parse(
                model=self._model,
                input=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": user_prompt,
                    },
                ],
                timeout=request_timeout,
                **parse_kwargs,
            )

        except TimeoutError as exc:
            raise LLMTimeoutError("OpenAI request timed out") from exc

        except APITimeoutError as exc:
            raise LLMTimeoutError("OpenAI request timed out") from exc

        except APIConnectionError as exc:
            raise LLMNetworkError("OpenAI network error") from exc

        except InternalServerError as exc:
            raise LLMNetworkError("OpenAI internal server error") from exc

        except AuthenticationError as exc:
            raise LLMAuthenticationError("OpenAI authentication error") from exc

        except RateLimitError as exc:
            raise LLMNetworkError("OpenAI rate limit exceeded") from exc

        except APIError as exc:
            raise LLMNetworkError(f"OpenAI API error: {exc}") from exc

        try:
            parsed = response.output_parsed
            if parsed is None:
                raise LLMInvalidResponseError(
                    "OpenAI returned unexpected response format: missing parsed output"
                )

            return parsed.model_dump_json()

        except AttributeError as exc:
            raise LLMInvalidResponseError("OpenAI returned unexpected response format") from exc
