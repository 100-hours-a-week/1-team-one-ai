# app/data/loader.py

"""
운동 데이터 저장소
- exercises.json 로드 및 캐싱
- exerciseId 집합 관리 (유효성 검증용)
- raw dict 데이터 제공 (LLM 프롬프트용)
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.core.config import settings
from app.schemas.v1.exercise import Exercise

logger = logging.getLogger(__name__)


def fetch_and_save_exercises(
    url: str = settings.EXERCISE_API_URL,
    path: Path = settings.EXERCISES_PATH,
) -> None:
    """
    운동 데이터를 외부 API에서 받아와서 JSON으로 저장.

    Args:
    - url: 운동 데이터 API URL

    Raises:
    - httpx.RequestError: 네트워크 오류
    - httpx.HTTPStatusError: HTTP 에러 응답
    - ValueError: 잘못된 응답 형식
    - 일단은 다 raise error 하고 main에서 try/catch로 처리
    """
    try:
        response = httpx.get(
            url,
            timeout=httpx.Timeout(10.0),
            follow_redirects=True,
        )
        response.raise_for_status()

        data = response.json()

        if not isinstance(data, list):
            raise ValueError("Invalid response format: expected list")

    except httpx.RequestError:
        raise

    except httpx.HTTPStatusError:
        raise

    except (ValueError, json.JSONDecodeError):
        raise

    # 모든 검증을 통과한 경우에만 파일 저장
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info("Exercises 데이터 fetch 및 로드 완료: %s", path)


@dataclass
class ExerciseRepository:
    """
    운동 데이터 저장소

    책임:
    - exercises.json 로드 및 캐싱
    - exerciseId 집합 관리 (유효성 검증용)
    - raw dict 데이터 제공 (LLM 프롬프트용)
    """

    _exercises: tuple[Exercise, ...] = field(default_factory=tuple)
    _exercise_ids: frozenset[str] = field(default_factory=frozenset)
    _raw_data: list[dict] = field(default_factory=list)
    _loaded: bool = False

    def _ensure_loaded(self) -> None:
        """로드 여부 확인 후 자동 로드."""
        if not self._loaded:
            self.load()

    def load(self, path: Path = settings.EXERCISES_PATH) -> None:
        """
        exercises.json을 로드하고 캐싱.

        Args:
        - path: exercises.json 경로

        Raises:
        - FileNotFoundError: 파일이 없을 때
        - ~~ValidationError: 스키마 검증 실패 시~~
            -> 스키마 검증 실패 시 로드 중단
        """
        # 순수 로더로 수정
        # if self._loaded:
        #    logger.debug("Exercises already loaded, skipping")
        #    return

        if not path.exists():
            raise FileNotFoundError(f"exercises.json not found: {path}")

        with path.open(encoding="utf-8") as f:
            data: list[dict] = json.load(f)

        # Pydantic 검증 - 실패 시 raise error & 로드 중단
        exercises = tuple(Exercise.model_validate(e) for e in data)

        # 캐싱
        self._exercises = exercises
        self._exercise_ids = frozenset(ex.exerciseId for ex in exercises)
        self._raw_data = [ex.model_dump(by_alias=True) for ex in exercises]
        self._loaded = True

        logger.info(
            "Exercises data 리로드 완료: %d 개 운동, %d unique IDs",
            len(exercises),
            len(self._exercise_ids),
        )

    @property
    def exercise_ids(self) -> frozenset[str]:
        """유효한 exerciseId 집합 (유효성 검증용)."""
        self._ensure_loaded()
        return self._exercise_ids

    @property
    def raw_data(self) -> list[dict]:
        """원본 dict 리스트 (LLM 프롬프트용)."""
        self._ensure_loaded()
        return self._raw_data

    def is_valid(self) -> bool:
        """운동 데이터가 정상적으로 로드되었는지 확인 (health check용)."""
        return self._loaded and len(self._exercise_ids) > 0

    def is_valid_exercise_id(self, exercise_id: str) -> bool:
        """exerciseId 유효성 검사."""
        self._ensure_loaded()
        return exercise_id in self._exercise_ids


# 싱글톤 인스턴스 (앱 전역에서 사용)
exercise_repository = ExerciseRepository()
