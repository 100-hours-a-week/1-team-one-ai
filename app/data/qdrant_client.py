# app/data/qdrant_client.py
"""
QdrantClient 싱글턴 관리

get_qdrant_client() → QdrantClient
  - QDRANT_URL 환경변수로 대상 인스턴스 선택
    - dev  : http://localhost:6333  (기본값, api_key 불필요)
    - live : https://xxx.qdrant.io  (QDRANT_API_KEY 필수)
  - 최초 호출 시 1회 생성, 이후 캐시된 인스턴스 반환

verify_connection() → tuple[bool, str]
  - 실제 네트워크 통신으로 연결 상태 확인 (진단 API / 헬스체크용)

record_collection_update(collection_name) → None
  - upsert 성공 시 Repository에서 호출 — 컬렉션별 최신 업데이트 시각 기록
  - 프로세스 메모리에 저장하므로 서버 재기동 시 초기화됨

get_collection_updated_at(collection_name) → datetime | None
  - 기록된 마지막 업데이트 시각 반환. 이번 기동 후 upsert가 없으면 None
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from qdrant_client import QdrantClient

from app.core.config import settings

logger = logging.getLogger(__name__)


_client: QdrantClient | None = None  # QdrantClient 싱글턴
_collection_updated_at: dict[str, datetime] = {}  # 컬렉션별 마지막 upsert 시각 (프로세스 메모리)


def get_qdrant_client() -> QdrantClient:
    """
    QdrantClient 싱글턴 반환.

    QDRANT_URL  : 연결 대상 (기본값 http://localhost:6333)
    QDRANT_API_KEY : 클라우드 인스턴스용 (로컬은 None으로 생략)
    """
    global _client

    if _client is None:
        _client = QdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY or None,  # 빈 문자열도 None으로 처리 (로컬 호환)
        )
        logger.info("QdrantClient 연결: %s", settings.QDRANT_URL)

    return _client


def verify_connection() -> tuple[bool, str]:
    """Qdrant 연결 상태를 실제 네트워크 통신으로 확인한다.

    get_qdrant_client()는 QdrantClient 객체만 생성하므로 연결 여부를 알 수 없다.
    이 함수는 get_collections()를 호출해 실제 통신이 성공하는지 검증한다.

    Returns:
        (True, "") — 연결 성공
        (False, "에러 설명") — 연결 실패
    """
    from app.data.qdrant_exceptions import (
        QdrantAuthError,
        QdrantConnectionError,
        QdrantError,
        translate_qdrant_error,
    )

    try:
        client = get_qdrant_client()
        client.get_collections()
        return True, ""

    except Exception as raw_exc:
        translated = translate_qdrant_error(raw_exc)

        if isinstance(translated, QdrantAuthError):
            return False, f"인증 오류: {translated}"

        if isinstance(translated, QdrantConnectionError):
            return False, f"연결 실패: {translated}"

        if isinstance(translated, QdrantError):
            return False, f"Qdrant 오류: {translated}"

        return False, f"알 수 없는 오류: {raw_exc}"


def record_collection_update(collection_name: str) -> None:
    """컬렉션 upsert 성공 직후 Repository에서 호출한다.

    Qdrant API는 컬렉션 레벨의 업데이트 시각을 반환하지 않으므로
    프로세스 메모리에서 직접 추적한다.

    주의: 서버 재기동 시 초기화됨. 재기동 후 첫 upsert 전까지 None 반환.
    """
    _collection_updated_at[collection_name] = datetime.now(timezone.utc)


def get_collection_updated_at(collection_name: str) -> datetime | None:
    """컬렉션의 마지막 upsert 시각을 반환한다.

    Returns:
        datetime (UTC) — 이번 프로세스 기동 후 upsert가 1회 이상 성공한 경우
        None            — 재기동 후 upsert가 없거나 컬렉션이 존재하지 않는 경우
    """
    return _collection_updated_at.get(collection_name)
