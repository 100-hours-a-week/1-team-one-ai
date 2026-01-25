# app/configs/llm_config.py

"""
LLM 설정 로더
- llm.yaml 파싱 및 Pydantic 모델 변환
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from app.core.exceptions import ConfigurationError

CONFIG_PATH = Path(__file__).parent / "llm.yaml"


class ProviderConfig(BaseModel):
    """LLM 프로바이더 설정."""

    spec: Literal["openai_compatible", "gemini_native"]
    auth: Literal["api_key", "none"]
    base_url: str | None = None
    model: str
    timeout_sec: int = 30
    retry: int = Field(default=2, ge=0, le=5)


class LLMConfig(BaseModel):
    """전체 LLM 설정."""

    default_provider: str
    providers: dict[str, ProviderConfig]
    fallback: bool


def load_llm_config() -> LLMConfig:
    """
    llm.yaml 파일을 로드하여 LLMConfig 반환

    Raise:
    - ConfigurationError: 설정 파일 로드 또는 검증 실패
    """
    try:
        with CONFIG_PATH.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return LLMConfig.model_validate(data)

    except FileNotFoundError as e:
        raise ConfigurationError(f"LLM 설정 파일 없음: {CONFIG_PATH}") from e

    except yaml.YAMLError as e:
        raise ConfigurationError(f"LLM 설정 YAML 파싱 실패: {e}") from e

    except ValidationError as e:
        raise ConfigurationError(f"LLM 설정 스키마 검증 실패: {e}") from e


# 싱글톤 인스턴스 (앱 시작 시 한 번만 로드)
llm_config = load_llm_config()
