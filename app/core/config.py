# app/core/config.py
"""
환경변수 관리
- class Settings(BaseSettings)
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENV: str = "dev"

    OPENAI_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    OLLAMA_API_KEY: str | None = None

    LLM_BASE_URL: str | None = None


settings = Settings()


class RoutineTimePolicy:
    """
    루틴 총 시간 정책 (초 단위)

    - MIN_TIME: 최소 시간 (150초 = 2분 30초)
    - MAX_TIME: 최대 시간 (210초 = 3분 30초)
    - TARGET_TIME: 목표 시간 (180초 = 3분)
    """

    MIN_TIME: int = 150  # 2분 30초
    MAX_TIME: int = 210  # 3분 30초
    TARGET_TIME: int = 180  # 3분
