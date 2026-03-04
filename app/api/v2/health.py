# app/api/v2/health.py
"""
헬스 체크 API (v2)
- GET /health

v1 대비 추가 항목:
  - qdrant: 벡터DB 연결 상태

상태 판단 기준:
  - 모든 서비스 정상       → HEALTHY
  - 하나 이상 비정상       → DEGRADED  (룰베이스 추천은 항상 가능하므로 UNHEALTHY 없음)
  - 서버가 응답하는 한 항상 200 반환

서비스별 의미:
  - exercises : exercises.json 로드 상태. 다운 시 LLM 프롬프트 데이터 없음 → DEGRADED
  - qdrant    : 벡터DB 연결 상태. 다운 시 벡터 upsert·cold start 판단 불가 → DEGRADED
"""

from datetime import datetime, timezone

from fastapi import APIRouter

from app.data.loader import exercise_repository
from app.data.qdrant_client import verify_connection
from app.schemas.common import HealthResponse, HealthStatus

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """
    V2 서비스 헬스 체크.

    verify_connection()이 실제 네트워크 통신을 수행하므로 sync def 사용.
    FastAPI가 스레드풀에서 실행하여 event loop 블로킹을 방지한다.

    - Raise: None
    - HTTP Status: 200 OK
    """
    # 1. exercises — LLM 프롬프트용 데이터 로드 여부
    exercises_status = (
        HealthStatus.HEALTHY if exercise_repository.is_valid() else HealthStatus.DEGRADED
    )

    # 2. qdrant — 벡터DB 연결 여부 (선택적 의존성)
    qdrant_ok, _ = verify_connection()
    qdrant_status = HealthStatus.HEALTHY if qdrant_ok else HealthStatus.DEGRADED

    # 전체 상태: 하나라도 degraded면 degraded (UNHEALTHY 없음 — 룰베이스 추천 항상 가능)
    all_healthy = exercises_status == HealthStatus.HEALTHY and qdrant_status == HealthStatus.HEALTHY
    overall = HealthStatus.HEALTHY if all_healthy else HealthStatus.DEGRADED

    return HealthResponse(
        status=overall,
        version="v2.0.0",
        timestamp=datetime.now(timezone.utc),
        services={
            "api": HealthStatus.HEALTHY,
            "exercises": exercises_status,
            "qdrant": qdrant_status,
        },
    )
