# tests/services/llm_clients/test_openai_client.py

"""OpenAI 클라이언트 테스트.

pytest -v -s tests/services/llm_clients/test_openai_client.py
"""

import pytest
from pydantic import BaseModel

from app.core.config import settings
from app.services.llm_clients.base import LLMNetworkError
from app.services.llm_clients.openai_client import OpenAIClient

SYSTEM_PROMPT = "You are a helpful assistant."
USER_PROMPT = "Say hi."

RATE_LIMIT_PATTERNS = ("rate limit", "quota")


def is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(p in msg for p in RATE_LIMIT_PATTERNS)


class SimpleResponse(BaseModel):
    """테스트용 응답 스키마."""

    message: str


class TestOpenAIClientInstantiation:
    """OpenAI 클라이언트 인스턴스 생성 테스트."""

    def test_client_instantiation_with_api_key(self) -> None:
        """API 키로 클라이언트 생성."""

        client = OpenAIClient(api_key="test-api-key")
        assert client is not None
        assert client._model == "gpt-4.1-mini"  # 기본값
        assert client._default_timeout == 30.0  # 기본값

    def test_client_instantiation_with_custom_params(self) -> None:
        """커스텀 파라미터로 클라이언트 생성."""

        client = OpenAIClient(
            api_key="test-api-key",
            model="gpt-4o",
            default_timeout=60.0,
        )

        assert client._model == "gpt-4o"
        assert client._default_timeout == 60.0


class TestOpenAIClientGenerate:
    """OpenAI 클라이언트 generate 메서드 테스트 (실제 API 호출)."""

    def test_generate_basic(self) -> None:
        """기본 generate 테스트 (실제 API 호출)."""
        api_key = settings.OPENAI_API_KEY
        if not api_key:
            pytest.skip("OPENAI_API_KEY not set")

        client = OpenAIClient(api_key=api_key)

        try:
            result = client.generate(SYSTEM_PROMPT, USER_PROMPT, timeout=10.0)
            assert isinstance(result, str)
            assert len(result) > 0
        except LLMNetworkError as e:
            if is_rate_limit_error(e):
                pytest.skip("OpenAI rate limit / quota exceeded")
            raise

    def test_generate_with_response_schema(self) -> None:
        """response_schema를 사용한 generate 테스트."""
        api_key = settings.OPENAI_API_KEY
        if not api_key:
            pytest.skip("OPENAI_API_KEY not set")

        client = OpenAIClient(api_key=api_key)

        try:
            result = client.generate(
                system_prompt="You are a helpful assistant. Respond with a simple greeting.",
                user_prompt="Say hello",
                response_schema=SimpleResponse,
                timeout=15.0,
            )
            assert isinstance(result, str)
            # JSON 형식인지 확인
            assert "{" in result
        except LLMNetworkError as e:
            if is_rate_limit_error(e):
                pytest.skip("OpenAI rate limit / quota exceeded")
            raise

    def test_generate_with_custom_timeout(self) -> None:
        """커스텀 타임아웃으로 generate 테스트."""
        api_key = settings.OPENAI_API_KEY
        if not api_key:
            pytest.skip("OPENAI_API_KEY not set")

        client = OpenAIClient(api_key=api_key)

        try:
            result = client.generate(
                SYSTEM_PROMPT,
                USER_PROMPT,
                timeout=5.0,  # 짧은 타임아웃
            )
            assert isinstance(result, str)

        except LLMNetworkError as e:
            if is_rate_limit_error(e):
                pytest.skip("OpenAI rate limit / quota exceeded")
            raise
