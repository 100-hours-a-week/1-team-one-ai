"""Qdrant 관련 예외 계층 및 SDK 예외 번역."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class UpsertErrorType(str, Enum):
    AUTH = "AUTH_ERROR"
    SERVER = "SERVER_ERROR"
    COLLECTION = "COLLECTION_NOT_FOUND"
    CONNECTION = "CONNECTION_ERROR"
    UNKNOWN = "UNKNOWN_ERROR"


@dataclass
class UpsertResult:
    upserted: int
    error_type: Optional[UpsertErrorType] = field(default=None)
    error_message: Optional[str] = field(default=None)

    @property
    def state(self) -> Optional[dict]:
        """라우터 응답용 state 딕셔너리. 에러 없으면 None."""
        if self.error_type is None:
            return None
        return {"errorType": self.error_type, "errorMessage": self.error_message}


class QdrantError(Exception):
    """Qdrant 관련 예외 기반 클래스."""


class QdrantConnectionError(QdrantError):
    """네트워크 단절 / 서버 unreachable / 타임아웃."""


class QdrantServerError(QdrantError):
    """Qdrant 서버 5xx 응답."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class QdrantAuthError(QdrantError):
    """API 키 없음 / 권한 부족 (401, 403)."""


class QdrantCollectionError(QdrantError):
    """컬렉션 없음 또는 스키마 불일치 (404)."""


def upsert_error_to_http_status(error_type: UpsertErrorType) -> int:
    """UpsertErrorType → HTTP 상태 코드 매핑.

    - COLLECTION: 500 (컬렉션 미존재 = 서버 설정 오류)
    - 나머지: 503 (Qdrant 서비스 불가)
    """
    if error_type == UpsertErrorType.COLLECTION:
        return 500
    return 503


def translate_qdrant_error(e: Exception) -> QdrantError:
    """qdrant-client SDK 예외를 앱 예외 계층으로 변환.

    호출 패턴:
        except Exception as e:
            raise translate_qdrant_error(e) from e
    """
    try:
        from qdrant_client.http.exceptions import UnexpectedResponse

        if isinstance(e, UnexpectedResponse):
            sc = e.status_code
            if sc in (401, 403):
                return QdrantAuthError(f"Qdrant 인증 실패 (HTTP {sc})")
            if sc == 404:
                return QdrantCollectionError(f"컬렉션 없음 (HTTP {sc}): {e.content}")
            if sc is not None and 500 <= sc < 600:
                return QdrantServerError(
                    f"Qdrant 서버 오류 (HTTP {sc})", status_code=sc
                )
    except ImportError:
        pass

    err_lower = str(e).lower()
    if any(k in err_lower for k in ("connect", "timeout", "refused", "unreachable", "network")):
        return QdrantConnectionError(f"Qdrant 연결 실패: {e}")

    return QdrantConnectionError(f"Qdrant 알 수 없는 오류: {e}")
