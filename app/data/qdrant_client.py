# app/data/qdrant_client.py
"""
QdrantClient 싱글턴 / 연결 관리

TODO: Qdrant 연동 시 구현
- QdrantClient 싱글턴 인스턴스 생성
- 연결 설정 (host, port, api_key)
- 컬렉션 초기화 (user_activity_profiles, exercises)
"""

# TODO: Qdrant 연동 시 아래 구현 추가
#
# from qdrant_client import QdrantClient
# from app.core.config import settings
#
# _qdrant_client: QdrantClient | None = None
#
#
# def get_qdrant_client() -> QdrantClient:
#     """
#     QdrantClient 싱글턴 인스턴스 반환.
#     FastAPI lifespan 또는 DI 함수에서 호출합니다.
#     """
#     global _qdrant_client
#     if _qdrant_client is None:
#         _qdrant_client = QdrantClient(
#             url=settings.QDRANT_URL,
#             api_key=settings.QDRANT_API_KEY,
#         )
#     return _qdrant_client
