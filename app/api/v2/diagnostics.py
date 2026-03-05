# app/api/v2/diagnostics.py
"""
Qdrant 상태 진단 API

GET /diagnostics/qdrant
  - 연결 상태, 모니터링 컬렉션 목록·포인트 수를 반환
  - Qdrant 다운·인증 실패 등 에러 타입을 error_type 필드로 구분

GET /diagnostics/qdrant/{collection_name}
  - 특정 컬렉션의 존재 여부, 내부 벡터 수, 최신 업데이트 시간 반환
  - updated_at: 이번 프로세스 기동 후 upsert 성공 시각 (재기동 시 초기화)
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

MONITORED_COLLECTIONS = ["exercises", "user_activity_profiles"]


# ── Response Schema ───────────────────────────────────────────────────────────


class CollectionInfo(BaseModel):
    name: str
    status: str  # "ok" | "missing" | "error"
    points_count: int | None = None


class QdrantDiagnosticsResponse(BaseModel):
    status: str  # "ok" | "error"
    url: str
    error: str | None = None
    error_type: str | None = None  # "connection" | "auth" | "server" | "unknown"
    collections: list[CollectionInfo] = []


class CollectionDiagnosticsResponse(BaseModel):
    """특정 컬렉션의 상세 진단 응답.

    updated_at 주의사항:
      Qdrant API는 컬렉션 레벨 업데이트 시각을 반환하지 않는다.
      이 값은 이번 프로세스 기동 후 upsert가 성공할 때마다 앱 메모리에서 갱신된다.
      서버 재기동 시 초기화되므로, None이면 "재기동 후 upsert 없음"을 의미한다.
    """

    collection_name: str
    exists: bool
    points_count: int | None = None
    updated_at: datetime | None = None


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.get("/diagnostics/qdrant", response_model=QdrantDiagnosticsResponse)
def qdrant_diagnostics() -> QdrantDiagnosticsResponse:
    """
    Qdrant 연결 상태 및 컬렉션 정보를 반환한다.

    - status="error" : 연결·인증·서버 오류. error_type으로 원인 구분
    - status="ok"    : 연결 성공. collections 목록에 각 컬렉션 상태 포함
    """
    from app.core.config import settings
    from app.data.qdrant_client import get_qdrant_client, verify_connection
    from app.data.qdrant_exceptions import QdrantAuthError, QdrantConnectionError, QdrantServerError

    url = settings.QDRANT_URL
    ok, err_msg = verify_connection()

    if not ok:
        if isinstance(_classify_error(err_msg), QdrantAuthError):
            error_type = "auth"
        elif isinstance(_classify_error(err_msg), QdrantConnectionError):
            error_type = "connection"
        elif isinstance(_classify_error(err_msg), QdrantServerError):
            error_type = "server"
        else:
            error_type = "unknown"

        return QdrantDiagnosticsResponse(
            status="error",
            url=url,
            error=err_msg,
            error_type=error_type,
        )

    # 연결 성공 → 컬렉션별 상태 수집
    client = get_qdrant_client()
    collection_infos: list[CollectionInfo] = []

    for col in MONITORED_COLLECTIONS:
        try:
            if client.collection_exists(col):
                info = client.get_collection(col)
                collection_infos.append(
                    CollectionInfo(
                        name=col,
                        status="ok",
                        points_count=info.points_count,
                    )
                )
            else:
                collection_infos.append(CollectionInfo(name=col, status="missing"))

        except Exception as e:
            logger.warning("컬렉션 %s 조회 실패: %s", col, e)
            collection_infos.append(CollectionInfo(name=col, status="error"))

    return QdrantDiagnosticsResponse(
        status="ok",
        url=url,
        collections=collection_infos,
    )


@router.get("/diagnostics/qdrant/{collection_name}", response_model=CollectionDiagnosticsResponse)
def qdrant_collection_diagnostics(collection_name: str) -> CollectionDiagnosticsResponse:
    """
    특정 컬렉션의 상세 진단 정보를 반환한다.

    - exists=False : 컬렉션이 Qdrant에 없음 (points_count, updated_at 모두 None)
    - exists=True  : points_count와 updated_at 포함
    - updated_at   : 이번 프로세스 기동 후 첫 upsert 전이면 None
    """
    from app.data.qdrant_client import (
        get_collection_updated_at,
        get_qdrant_client,
        verify_connection,
    )

    ok, err_msg = verify_connection()
    if not ok:
        logger.warning(
            "컬렉션 진단 요청 실패 — Qdrant 연결 불가 [%s]: %s", collection_name, err_msg
        )
        return CollectionDiagnosticsResponse(collection_name=collection_name, exists=False)

    client = get_qdrant_client()

    try:
        if not client.collection_exists(collection_name):
            return CollectionDiagnosticsResponse(collection_name=collection_name, exists=False)

        info = client.get_collection(collection_name)
        return CollectionDiagnosticsResponse(
            collection_name=collection_name,
            exists=True,
            points_count=info.points_count,
            updated_at=get_collection_updated_at(collection_name),
        )
    except Exception as e:
        logger.warning("컬렉션 %s 조회 실패: %s", collection_name, e)
        return CollectionDiagnosticsResponse(collection_name=collection_name, exists=False)


def _classify_error(err_msg: str) -> Exception:
    """verify_connection()의 에러 메시지로 에러 타입을 추론한다."""
    from app.data.qdrant_exceptions import (
        QdrantAuthError,
        QdrantConnectionError,
        QdrantServerError,
    )

    if "인증" in err_msg:
        return QdrantAuthError(err_msg)
    if "연결" in err_msg:
        return QdrantConnectionError(err_msg)
    if "서버" in err_msg:
        return QdrantServerError(err_msg, status_code=500)
    return QdrantConnectionError(err_msg)
