# 1. 로깅 설정 — 라우터 import 전에 실행해야 외부 라이브러리 로그 억제가 적용됨
# (라우터 import 시 deps.py가 실행되어 httpx 등이 로그를 출력할 수 있음)
import logging
from app.core.logging import setup_logging

setup_logging()

import os

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import ValidationError

from app.api.deps import get_exercise_vector_service
from app.api.v1.router import router as v1_router
from app.api.v2.router import router as v2_router
from app.api.v3.router import router as v3_router
from app.core.exceptions import (
    AppError,  # 500
    app_error_handler,  # AppError 통합 핸들러
    internal_exception_handler,  # 500
    validation_exception_handler,  # 422
)
from app.data.loader import exercise_repository, fetch_and_save_exercises

logger = logging.getLogger(__name__)

logger.info("APP_ENV=%s", os.environ.get("APP_ENV", "dev"))

# 2. 운동 데이터 로드 (settings.EXERCISE_API_URL 사용)
try:
    fetch_and_save_exercises()
    logger.info("운동 데이터 fetch 완료")

except Exception as e:
    logger.warning("운동 데이터 fetch 실패: %s\n기존 exercises.json 사용...", e)

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

# 4. 운동 벡터 upsert (Qdrant 연결 시)
result = get_exercise_vector_service().try_upsert_all(exercise_repository.raw_data)
if result.upserted > 0:
    logger.info("운동 벡터 upsert 완료: %d개", result.upserted)
elif result.error_type:
    logger.warning("운동 벡터 upsert 실패: %s — %s", result.error_type, result.error_message)


app = FastAPI(
    title="Recommendation API",
    version="1.1.0",
)


Instrumentator().instrument(app).expose(app)

app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore
app.add_exception_handler(AppError, app_error_handler)  # type: ignore  # AppError 하위 클래스 처리
app.add_exception_handler(Exception, internal_exception_handler)  # 마지막: fallback


app.include_router(v1_router, prefix="/api/v1")
app.include_router(v2_router, prefix="/api/v2")
app.include_router(v3_router, prefix="/api/v3")


@app.get("/")
async def root():
    return {"status": "ok"}
