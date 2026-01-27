import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import ValidationError

from app.api.v1.router import router as v1_router
from app.core.exceptions import (
    AppError,  # 500
    app_error_handler,  # 새로 추가: AppError 통합 핸들러
    internal_exception_handler,  # 500
    validation_exception_handler,  # 422
)
from app.core.logging import setup_logging
from app.data.loader import exercise_repository, fetch_and_save_exercises

logger = logging.getLogger(__name__)

# 1. 로깅 설정
setup_logging()

# 2. 운동 데이터 로드 (settings.EXERCISE_API_URL 사용)
try:
    fetch_and_save_exercises()

except Exception as e:
    logger.warning("운동 데이터 fetch 실패, 기존 exercises.json 사용: %s", e)

# 3. 운동 데이터 검증
try:
    exercise_repository.load()
    logger.info("운동 데이터 로드 완료: %d개", len(exercise_repository.exercise_ids))
except FileNotFoundError as e:
    logger.error("exercises.json 파일 없음: %s", e)
except ValidationError as e:
    logger.error("exercises.json 검증 실패: %s", e)
except Exception as e:
    logger.error("운동 데이터 로드 실패: %s", e)


app = FastAPI(
    title="Recommendation API",
    version="1.0.0",
)

Instrumentator().instrument(app).expose(app)

app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore
app.add_exception_handler(AppError, app_error_handler)  # type: ignore  # AppError 하위 클래스 처리
app.add_exception_handler(Exception, internal_exception_handler)  # 마지막: fallback


app.include_router(v1_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {"status": "ok"}
