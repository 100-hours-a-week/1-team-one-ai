# app/core/exceptions.py
"""
공통 예외 정의
- class ServiceUnavailableError(Exception)
- async def validation_exception_handler()
- async def internal_exception_handler()
- async def service_unavailable_handler()

"""

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas.common import ErrorDetail, ErrorResponse

# app/core/exceptions.py
"""
공통 예외 정의
- HTTP 상태 코드를 가진 애플리케이션 예외 계층
- 전역 예외 핸들러
"""


class AppError(Exception):
    """
    애플리케이션 공통 베이스 예외
    - 모든 도메인/서비스 예외의 부모
    - HTTP status code와 error code를 가짐
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str = "unexpected error") -> None:
        super().__init__(message)
        self.message = message


# ============================================================
# 비즈니스 로직 예외 (500)
# ============================================================


class RoutineValidationError(AppError):
    """루틴 유효성 검증 실패 예외 - 500"""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code = "ROUTINE_VALIDATION_ERROR"

    def __init__(self, message: str, invalid_routines: list[int] | None = None) -> None:
        super().__init__(message)
        self.invalid_routines = invalid_routines or []


class ConfigurationError(AppError):
    """
    서버 설정 오류 - 500
    - llm.yaml is missing or malformed
    - Provider configuration is invalid
    - Required environment variables missing
    """

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code = "CONFIGURATION_ERROR"


# ============================================================
# 의존 서비스 예외 (503)
# ============================================================


class DependencyNotReadyError(AppError):
    """
    의존 서비스 준비 안됨 - 503
    - DI functions are not implemented
    - External service is unavailable at startup
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "DEPENDENCY_NOT_READY"


class ServiceUnavailableError(AppError):
    """핵심 의존 서비스 사용 불가 - 503"""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "SERVICE_UNAVAILABLE"


# ============================================================
# 전역 예외 핸들러
# ============================================================


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """
    AppError 및 하위 예외 처리
    - LLMError, ConfigurationError, RoutineValidationError 등 모두 처리
    """
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            code=exc.error_code,
            errors=[ErrorDetail(reason=exc.message)],
        ).model_dump(exclude_none=True),
    )


async def service_unavailable_handler(
    request: Request, exc: ServiceUnavailableError
) -> JSONResponse:
    """
    상세 헬스체크 api 요청 시 핵심 의존 서비스 사용 불가
    - 503: 핵심 의존 서비스 사용 불가
    """

    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=ErrorResponse(
            code="SERVICE_UNAVAILABLE",
            errors=[ErrorDetail(reason="one or more core dependent services are unavailable")],
        ).model_dump(exclude_none=True),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Request Body Pydantic 유효성 검사 실패 시 커스텀 에러 응답 반환
    - 422: 필수 필드 누락
    - 400: 그 외 유효성 검사 실패 (추가 필드 등)
    """

    errors = exc.errors()

    # missing 에러가 있는지 확인
    missing_errors = [e for e in errors if e.get("type") == "missing"]

    if missing_errors:
        # 422 - 필수 필드 누락
        missing_fields = [str(e["loc"][-1]) for e in missing_errors if e.get("loc")]
        code = "_".join(f.upper() for f in missing_fields) + "_MISSING"
        error_details = [
            ErrorDetail(field=str(e["loc"][-1]), reason="missing request field values")
            for e in missing_errors
            if e.get("loc")
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorResponse(code=code, errors=error_details).model_dump(exclude_none=True),
        )

    # 400 - 그 외 유효성 검사 실패 (추가 필드 등)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=ErrorResponse(
            code="INVALID_JSON",
            errors=[ErrorDetail(reason="json format is invalid")],
        ).model_dump(exclude_none=True),
    )


async def internal_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Request 시 internal server error 발생
    - 500: 서버 내부 에러
    """

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            code="INTERNAL_ERROR",
            errors=[ErrorDetail(reason="unexpected error")],
        ).model_dump(exclude_none=True),
    )
