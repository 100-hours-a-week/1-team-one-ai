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


class ExpectedServiceError(Exception):
    """
    예상 가능한 모든 error
    HTTP 200 (FAILED)
    """

    pass


class RoutineValidationError(ExpectedServiceError):
    """루틴 유효성 검증 실패 예외"""

    def __init__(self, message: str, invalid_routines: list[int] | None = None) -> None:
        super().__init__(message)
        self.invalid_routines = invalid_routines or []


class ConfigurationError(ExpectedServiceError):
    """
    config load 깨질 때 raise 하는 에러
    - llm.yaml is missing or malformed
    - Provider configuration is invalid
    - Required environment variables missing
    """

    pass


class DependencyNotReadyError(ExpectedServiceError):
    """
    DI 구현 전 에러
    - DI functions are not implemented
    - External service is unavailable at startup
    """

    pass


class ServiceUnavailableError(Exception):
    """503 - 핵심 의존 서비스 사용 불가"""

    pass


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
