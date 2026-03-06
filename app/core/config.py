# app/core/config.py
"""
환경변수 관리
- class Settings(BaseSettings)
"""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 기본 경로 상수 — __file__ 기준 상대 계산이므로 이 파일 안에서만 유효 (이동 불가)
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

    # Qdrant
    QDRANT_URL: str = "https://stage.raisedeveloper.com:6333"
    QDRANT_API_KEY: str | None = None  # 로컬 불필요, 클라우드 필수
    QDRANT_EMBEDDING_MODEL: str = "intfloat/multilingual-e5-small"


settings = Settings()


class CallbackPolicy:
    """
    콜백 전송 정책

    - TIMEOUT_SEC: 콜백 HTTP 요청 타임아웃 (초)
    - MAX_RETRIES: 최대 재시도 횟수 (초기 시도 제외)
    """

    TIMEOUT_SEC: int = 10  # UP: 느린 coreBE 허용·worker 점유↑, DOWN: 타임아웃 에러↑
    MAX_RETRIES: int = 1  # 총 대기 = TIMEOUT_SEC × (MAX_RETRIES + 1) / 0이면 재시도 없음 (첫 1회 후 바로 실패 처리)


class RoutineTimePolicy:
    """
    루틴 총 시간 정책 (초 단위)

    - MIN_TIME: 최소 시간 (150초 = 2분 30초)
    - MAX_TIME: 최대 시간 (210초 = 3분 30초)
    - TARGET_TIME: 목표 시간 (180초 = 3분)

    주의: MIN_TIME ≤ TARGET_TIME ≤ MAX_TIME 을 반드시 만족해야 함
    """

    MIN_TIME: int = 150  # 2분 30초 (UP: 운동 추가 보완 잦아짐, DOWN: 짧은 루틴 허용)
    MAX_TIME: int = 210  # 3분 30초 (UP: 긴 루틴 허용, DOWN: 운동 제거 빈도 잦아짐)
    TARGET_TIME: int = 180  # 3분 — 시간 조정 목표점 (MIN <= TARGET <= MAX)
    DEFAULT_DURATION_TIME: int = (
        10  # totalDuration 미기재 운동 기본 수행 시간(초) — 루틴 총 시간 직접 영향
    )
    DEFAULT_TARGET_REPS: int = 10  # targetReps 미기재 REPS 운동 기본 반복 횟수 — 시간 추정에 영향
