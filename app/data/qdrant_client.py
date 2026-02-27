# app/data/qdrant_client.py
"""
QdrantClient 싱글턴 관리

get_qdrant_client() → QdrantClient
  - QDRANT_URL 환경변수로 대상 인스턴스 선택
    - dev  : http://localhost:6333  (기본값, api_key 불필요)
    - live : https://xxx.qdrant.io  (QDRANT_API_KEY 필수)
  - 최초 호출 시 1회 생성, 이후 캐시된 인스턴스 반환
"""

from __future__ import annotations

import logging

from qdrant_client import QdrantClient

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: QdrantClient | None = None


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
