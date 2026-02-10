# app/core/config.py
"""
환경변수 관리
- class Settings(BaseSettings)
"""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 기본 경로 상수
_BASE_DIR = Path(__file__).parent.parent  # app/
_PROJECT_ROOT = _BASE_DIR.parent  # project root
_DATA_DIR = _BASE_DIR / "data"
_DEFAULT_EXERCISES_PATH = _DATA_DIR / "exercises.json"


def _get_env_file() -> list[str]:
    """
    APP_ENV 환경변수에 따라 적절한 env 파일 선택
    - APP_ENV=dev → .env, .env.dev
    - APP_ENV=live → .env, .env.live
    - 기본값: dev
    """
    app_env = os.environ.get("APP_ENV", "dev").lower()
    env_file = f".env.{app_env}"
    return [".env", env_file]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_get_env_file(),
        extra="ignore",
    )

    # 환경 분기
    APP_ENV: str = "dev"

    # Logging
    LOG_LEVEL: str = "DEBUG"
    LOG_DIR: Path = _PROJECT_ROOT / "logs"
    LOG_FILE_NAME: str = "app.log"
    METRICS_ENABLED: bool = False

    # LLM Keys
    OPENAI_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    OLLAMA_API_KEY: str | None = None

    LLM_BASE_URL: str | None = None

    # API Security
    API_KEY: str | None = None

    # Exercise Data
    EXERCISE_API_URL: str | None = None
    EXERCISES_PATH: Path = _DEFAULT_EXERCISES_PATH

    # Callback
    CALLBACK_URL: str | None = None


settings = Settings()


class CallbackPolicy:
    """
    콜백 전송 정책

    - TIMEOUT_SEC: 콜백 HTTP 요청 타임아웃 (초)
    - MAX_RETRIES: 최대 재시도 횟수 (초기 시도 제외)
    """

    TIMEOUT_SEC: int = 10
    MAX_RETRIES: int = 1


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
    DEFAULT_DURATION_TIME: int = 10  # 10초
    DEFAULT_TARGET_REPS: int = 10  # 10회
