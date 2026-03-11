# app/services/satisfaction_service.py
"""
사용자 운동 만족도 Qdrant upsert 서비스

SatisfactionUpsertService
  - try_upsert_batch(records) → UpsertResult
    - 레코드를 userId 기준으로 그룹핑 후 Qdrant sparse vector upsert
    - Qdrant 미연결(repository=None) 시 CONNECTION error UpsertResult 반환
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from app.data.qdrant_exceptions import (
    QdrantAuthError,
    QdrantCollectionError,
    QdrantServerError,
    UpsertErrorType,
    UpsertResult,
)

if TYPE_CHECKING:
    from app.data.satisfaction_repository import SatisfactionRepository
    from app.schemas.v3.satisfaction import SatisfactionRecord

logger = logging.getLogger(__name__)


class SatisfactionUpsertService:
    """사용자 만족도 데이터를 Qdrant sparse vector로 upsert.

    - repository=None → CONNECTION error UpsertResult 반환
    - userId 기준으로 레코드를 그룹핑하여 사용자별 1회 upsert
    - 에러 종류별 로깅 전략:
      - Auth/Server 5xx → ERROR + exc_info=True
      - Collection/기타  → WARNING
    """

    def __init__(self, repository: SatisfactionRepository | None) -> None:
        self._repo = repository

    def try_upsert_batch(self, records: list[SatisfactionRecord]) -> UpsertResult:
        """만족도 레코드를 사용자별로 그룹핑하여 Qdrant에 upsert.

        Qdrant 미연결(repository=None) 시 CONNECTION error UpsertResult 반환.

        Args:
        - records: 만족도 레코드 목록 (userId, exerciseId, satisfaction)

        Returns:
        - UpsertResult(upserted=N): 성공한 사용자 수
        - UpsertResult(upserted=N, error_type=...) : 첫 에러 발생 시 즉시 반환
        """
        if self._repo is None:
            return UpsertResult(
                upserted=0,
                error_type=UpsertErrorType.CONNECTION,
                error_message="Qdrant 미연결 상태입니다. 만족도 데이터가 저장되지 않았습니다.",
            )

        # userId 기준으로 그룹핑
        user_satisfactions: dict[int, dict[int, float]] = defaultdict(dict)
        for record in records:
            user_satisfactions[record.userId][record.exerciseId] = float(
                record.satisfaction
            )

        upserted_count = 0
        for user_id, satisfactions in user_satisfactions.items():
            try:
                self._repo.upsert(user_id, satisfactions)
                upserted_count += 1
            except QdrantAuthError as e:
                logger.error(
                    "만족도 upsert 인증 실패 [user_id=%d]: %s", user_id, e, exc_info=True
                )
                return UpsertResult(
                    upserted=upserted_count,
                    error_type=UpsertErrorType.AUTH,
                    error_message=str(e),
                )
            except QdrantServerError as e:
                logger.error(
                    "만족도 upsert 서버 오류 [user_id=%d, status=%d]: %s",
                    user_id,
                    e.status_code,
                    e,
                    exc_info=True,
                )
                return UpsertResult(
                    upserted=upserted_count,
                    error_type=UpsertErrorType.SERVER,
                    error_message=str(e),
                )
            except QdrantCollectionError as e:
                logger.warning("만족도 upsert 컬렉션 오류 [user_id=%d]: %s", user_id, e)
                return UpsertResult(
                    upserted=upserted_count,
                    error_type=UpsertErrorType.COLLECTION,
                    error_message=str(e),
                )
            except Exception as e:
                logger.warning("만족도 upsert 실패 [user_id=%d]: %s", user_id, e)
                return UpsertResult(
                    upserted=upserted_count,
                    error_type=UpsertErrorType.CONNECTION,
                    error_message=str(e),
                )

        logger.info("만족도 upsert 완료: %d 명", upserted_count)
        return UpsertResult(upserted=upserted_count)
