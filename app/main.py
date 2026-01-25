import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.api.v1.router import router as v1_router
from app.core.exceptions import (
    ServiceUnavailableError,  # 503
    internal_exception_handler,  # 500
    service_unavailable_handler,  # 503
    validation_exception_handler,  # 422
)
from app.core.logging import setup_logging
from app.data.loader import exercise_repository, fetch_and_save_exercises

logger = logging.getLogger(__name__)

# 애플리케이션 초기화
exercise_api = "http://example.com/api"

# 1. 로깅 설정
setup_logging()

# 2. 운동 데이터 로드
try:
    fetch_and_save_exercises(exercise_api)

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

app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore
app.add_exception_handler(ServiceUnavailableError, service_unavailable_handler)  # type: ignore
app.add_exception_handler(Exception, internal_exception_handler)


app.include_router(v1_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {"status": "ok"}
