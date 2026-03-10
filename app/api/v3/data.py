# app/api/v3/data.py
"""
데이터 관리 API (v3) — router + endpoints only

DI 배선은 app/api/deps.py 참조.
- POST /update/satisfaction: 운동 만족도 배치 수신 → Qdrant sparse vector upsert

Qdrant 오류 시 503, 컬렉션 오류 시 500을 반환한다.
"""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import get_satisfaction_upsert_service
from app.data.qdrant_exceptions import upsert_error_to_http_status
from app.schemas.v3.satisfaction import BatchSatisfactionRequest
from app.services.satisfaction_service import SatisfactionUpsertService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/update/satisfaction", response_model=None)
async def update_satisfaction(
    body: BatchSatisfactionRequest,
    satisfaction_svc: SatisfactionUpsertService = Depends(get_satisfaction_upsert_service),
) -> dict | JSONResponse:
    """
    coreBE로부터 사용자 운동 만족도 데이터를 수신하여 Qdrant sparse vector upsert.

    [배치 시맨틱] Full Snapshot (덮어쓰기)
      - records에 포함된 userId의 만족도를 Qdrant에 전량 덮어씀.
      - coreBE는 배치 대상 사용자의 exercise_satisfactions 레코드를 전부 포함해야 함.
      - 일부만 전송하면 해당 사용자의 기존 만족도 데이터가 소실됨.

    흐름:
    1. 레코드를 userId 기준으로 그룹핑
    2. 사용자별 sparse vector 생성 → Qdrant upsert (exercise_satisfaction 컬렉션)
    3. Qdrant 오류 시 503/500 반환

    Args:
    - body: 만족도 레코드 배치 — exercise_satisfactions 테이블의 full snapshot
            (userId, exerciseId, satisfaction: +1 좋아요 | -1 싫어요)
    - satisfaction_svc: SatisfactionUpsertService (DI) → deps.get_satisfaction_upsert_service

    Returns:
        200: {"status": "ok", "upserted": N}
        503: {"status": "error", "upserted": N, "error": {...}} — Qdrant 연결/인증/서버 오류
        500: {"status": "error", "upserted": N, "error": {...}} — Qdrant 컬렉션 오류
    """
    upserted = satisfaction_svc.try_upsert_batch(body.records)
    body_resp = {
        "status": "error" if upserted.error_type else "ok",
        "upserted": upserted.upserted,
        "error": None
        if upserted.error_type is None
        else {"type": upserted.error_type, "message": upserted.error_message},
    }
    if upserted.error_type is not None:
        return JSONResponse(status_code=upsert_error_to_http_status(upserted.error_type), content=body_resp)
    return body_resp
