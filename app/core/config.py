# app/core/config.py
# 환경변수 관리

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ENV: str = "dev"

    OPENAI_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    OLLAMA_API_KEY: str | None = None

    LLM_BASE_URL: str | None = None

    class Config:
        env_file = ".env"


settings = Settings()
