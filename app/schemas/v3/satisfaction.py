# app/schemas/v3/satisfaction.py
"""
V3 사용자 만족도 스키마

coreBE가 exercise_satisfactions 테이블의 최신 상태를 배치로 전송할 때 사용.

[중요] 배치 시맨틱: full snapshot (덮어쓰기)
  - 전송 대상 사용자의 만족도를 ALL 포함해서 전송해야 한다.
  - 일부만 포함하면 Qdrant에 저장된 기존 데이터가 소실된다.
  - coreBE는 배치 대상 user_id의 exercise_satisfactions 레코드를 전량 포함할 것.

[RDB 매핑]
  exercise_satisfactions 테이블:
    user_id      → SatisfactionRecord.userId
    exercise_id  → SatisfactionRecord.exerciseId
    satisfaction → SatisfactionRecord.satisfaction  (tinyint: 1 or -1)
"""

from typing import Literal

from pydantic import BaseModel


class SatisfactionRecord(BaseModel):
    """단일 운동 만족도 레코드.

    RDB `exercise_satisfactions` 테이블의 행(row) 1건에 대응.
    satisfaction: +1 (좋아요) or -1 (싫어요)
    """

    userId: int
    exerciseId: int
    satisfaction: Literal[-1, 1]


class BatchSatisfactionRequest(BaseModel):
    """만족도 배치 수신 요청 (coreBE → AI 서버).

    records에 포함된 userId 기준으로 그룹핑 후 사용자별 Qdrant upsert.
    동일 userId가 여러 records에 포함된 경우 해당 사용자의 전체 만족도로 간주하여
    Qdrant 기존 벡터를 완전히 덮어쓴다.
    """

    records: list[SatisfactionRecord]
