# tests/services/llm_clients/test_ollama_client.py

"""Ollama 클라이언트 테스트.

pytest -v -s tests/services/llm_clients/test_ollama_client.py
"""

import logging

import pytest
from pydantic import BaseModel

from app.core.config import settings
from app.services.llm_clients.base import LLMNetworkError
from app.services.llm_clients.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "You are a helpful assistant."
USER_PROMPT = "Say hi."

RATE_LIMIT_PATTERNS = ("rate limit", "quota")


def is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(p in msg for p in RATE_LIMIT_PATTERNS)


class SimpleResponse(BaseModel):
    """테스트용 응답 스키마."""

    message: str


class TestOllamaClientInstantiation:
    """Ollama 클라이언트 인스턴스 생성 테스트."""

    def test_client_instantiation_with_api_key(self) -> None:
        """API 키로 클라이언트 생성."""
        logger.info("=== 테스트 시작: OllamaClient 인스턴스 생성 ===")

        client = OllamaClient(api_key="test-api-key")

        logger.info(f"클라이언트 생성됨: {type(client).__name__}")
        assert client is not None
        assert client._model == "gpt-oss:120b-cloud"  # 기본값
        assert client._default_timeout == 30.0  # 기본값
        logger.info("=== 테스트 완료: OllamaClient 인스턴스 생성 ===")

    def test_client_instantiation_with_custom_params(self) -> None:
        """커스텀 파라미터로 클라이언트 생성."""
        logger.info("=== 테스트 시작: OllamaClient 커스텀 파라미터 ===")

        client = OllamaClient(
            api_key="test-api-key",
            base_url="http://localhost:11434",
            model="llama2:13b",
            default_timeout=60.0,
        )

        logger.info(f"model: {client._model}")
        logger.info(f"default_timeout: {client._default_timeout}")

        assert client._model == "llama2:13b"
        assert client._default_timeout == 60.0
        logger.info("=== 테스트 완료: OllamaClient 커스텀 파라미터 ===")


class TestOllamaClientGenerate:
    """Ollama 클라이언트 generate 메서드 테스트 (실제 API 호출)."""

    def test_generate_basic(self) -> None:
        """기본 generate 테스트 (실제 API 호출)."""
        api_key = settings.OLLAMA_API_KEY
        if not api_key:
            pytest.skip("OLLAMA_API_KEY not set")

        logger.info("=== 테스트 시작: OllamaClient generate 기본 ===")

        client = OllamaClient(api_key=api_key)

        try:
            result = client.generate(SYSTEM_PROMPT, USER_PROMPT, timeout=10.0)
            logger.info(f"[Ollama] 응답: {result}")
            assert isinstance(result, str)
            assert len(result) > 0
        except LLMNetworkError as e:
            logger.info(f"[Ollama] 에러: {type(e).__name__}: {e}")
            if is_rate_limit_error(e):
                logger.info("Rate limit 에러 - 테스트 성공으로 처리")
                pytest.skip("Ollama rate limit / quota exceeded")
            raise

        logger.info("=== 테스트 완료: OllamaClient generate 기본 ===")

    def test_generate_with_response_schema(self) -> None:
        """response_schema를 사용한 generate 테스트."""
        api_key = settings.OLLAMA_API_KEY
        if not api_key:
            pytest.skip("OLLAMA_API_KEY not set")

        logger.info("=== 테스트 시작: OllamaClient generate with schema ===")

        client = OllamaClient(api_key=api_key)

        try:
            result = client.generate(
                system_prompt="You are a helpful assistant. Respond with a simple greeting in JSON format.",
                user_prompt="Say hello",
                response_schema=SimpleResponse,
                timeout=15.0,
            )
            logger.info(f"[Ollama] 응답 (schema): {result}")
            assert isinstance(result, str)
        except LLMNetworkError as e:
            logger.info(f"[Ollama] 에러: {type(e).__name__}: {e}")
            if is_rate_limit_error(e):
                logger.info("Rate limit 에러 - 테스트 성공으로 처리")
                pytest.skip("Ollama rate limit / quota exceeded")
            raise

        logger.info("=== 테스트 완료: OllamaClient generate with schema ===")

    def test_generate_with_custom_timeout(self) -> None:
        """커스텀 타임아웃으로 generate 테스트."""
        api_key = settings.OLLAMA_API_KEY
        if not api_key:
            pytest.skip("OLLAMA_API_KEY not set")

        logger.info("=== 테스트 시작: OllamaClient generate with timeout ===")

        client = OllamaClient(api_key=api_key)

        try:
            result = client.generate(
                SYSTEM_PROMPT,
                USER_PROMPT,
                timeout=5.0,  # 짧은 타임아웃
            )
            logger.info(f"[Ollama] 응답: {result}")
        except LLMNetworkError as e:
            logger.info(f"[Ollama] 에러: {type(e).__name__}: {e}")
            if is_rate_limit_error(e):
                logger.info("Rate limit 에러 - 테스트 성공으로 처리")
                pytest.skip("Ollama rate limit / quota exceeded")
            raise

        logger.info("=== 테스트 완료: OllamaClient generate with timeout ===")
