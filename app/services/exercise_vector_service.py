# app/services/exercise_vector_service.py
"""
운동 벡터 upsert 서비스

ExerciseVectorService
  - try_upsert_all(exercises) → None
    - passage 생성 → 임베딩 → PointStruct 구성 → repository.upsert_all()
    - Qdrant 미연결 / embedding_model 미설정 시 조용히 건너뜀 (silent skip)
    - 예외 발생 시 WARNING 로그 후 흐름 유지 (기존 API 영향 없음)

DI 조립 예시 (Qdrant 연동 완료 후):
    from sentence_transformers import SentenceTransformer
    from qdrant_client import QdrantClient
    from app.data.exercise_vector_repository import QdrantExerciseVectorRepository

    client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
    model  = SentenceTransformer("snunlp/KR-ELECTRA-discriminator")   # 또는 선택한 모델
    repo   = QdrantExerciseVectorRepository(client)
    svc    = ExerciseVectorService(repository=repo, embedding_model=model)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from qdrant_client import models

if TYPE_CHECKING:
    from app.data.exercise_vector_repository import ExerciseVectorRepository

logger = logging.getLogger(__name__)


# ── passage 생성 ──────────────────────────────────────────────────────────────


def _build_passage(ex: dict) -> str:
    """
    운동 dict → 임베딩용 자연어 passage.

    설문 query와 동일한 의미 공간에 사영되도록 동일한 prefix(passage:)를 사용합니다.
    """
    return (
        f"passage: 운동명: {ex['name']} | "
        f"부위: {ex['bodyPart']} | "
        f"효과: {ex['effect']} | "
        f"태그: {ex['tags']}"
    )


# ── ExerciseVectorService ─────────────────────────────────────────────────────


class ExerciseVectorService:
    """
    운동 데이터 → Qdrant 벡터 upsert 오케스트레이터.

    - embedding_model 또는 repository 가 None 이면 debug 로그 후 건너뜀
    - upsert 도중 예외 발생 시 WARNING 로그 후 건너뜀 (기존 API 흐름 영향 없음)
    """

    def __init__(
        self,
        repository: ExerciseVectorRepository | None,
        embedding_model: Any | None,  # SentenceTransformer 등 encode() 지원 모델
    ) -> None:
        self._repository = repository
        self._embedding_model = embedding_model

    # ── public ────────────────────────────────────────────────────────────────

    def try_upsert_all(self, exercises: list[dict]) -> None:
        """
        운동 목록 전체를 벡터DB에 upsert 합니다.

        - Qdrant 미연결 / 모델 미설정 시: DEBUG 로그 후 조용히 종료
        - 실행 중 예외 발생 시: WARNING 로그 후 조용히 종료
        - 기존 운동 데이터(exercises.json) 로드 흐름과 완전히 독립적으로 동작
        """
        if self._repository is None or self._embedding_model is None:
            logger.debug(
                "ExerciseVectorService: repository=%s, embedding_model=%s — 벡터 upsert 건너뜀",
                "설정됨" if self._repository else "미설정",
                "설정됨" if self._embedding_model else "미설정",
            )
            return

        try:
            points = self._build_points(exercises)
            count = self._repository.upsert_all(points)
            logger.info("exercises 벡터 upsert 완료: %d 개", count)
        except Exception as e:
            logger.warning(
                "exercises 벡터 upsert 실패 (Qdrant 미연결 또는 오류): %s",
                e,
                exc_info=False,
            )

    # ── private ───────────────────────────────────────────────────────────────

    def _build_points(self, exercises: list[dict]) -> list[models.PointStruct]:
        """
        운동 list[dict] → list[PointStruct].

        payload:
          - bodyPart, type, difficulty: 필터 검색용
          - completion_rate: 운동 자체의 평균 완료율
            TODO: coreBE 집계 데이터(exercise_results)로 실제 완료율 계산
                  현재는 전부 1.0 으로 초기화
        """
        points = []
        for ex in exercises:
            passage = _build_passage(ex)
            vector: list[float] = self._embedding_model.encode(passage).tolist()  # type: ignore

            point = models.PointStruct(
                id=ex["id"],  # exerciseId (int)
                vector=vector,
                payload={
                    "bodyPart": ex["bodyPart"],
                    "type": ex["type"],
                    "difficulty": ex["difficulty"],
                    "completion_rate": 1.0,  # TODO: 운동별 평균 완료율로 교체
                },
            )
            points.append(point)

        return points
