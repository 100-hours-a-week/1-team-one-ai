# app/domain/user_activity.py
"""
사용자 활동 프로필 도메인 엔티티
UserActivityProfile (preferred_body_parts, types, difficulty, activity_level)
"""

from __future__ import annotations

from dataclasses import dataclass

# ── 신체 부위별 운동 비율 ─────────────────────────────────────────────────


@dataclass(frozen=True)
class BodyPartDistribution:
    """신체 부위별 운동 비율 (합계 ≈ 1.0)"""

    neck: float = 0.0
    shoulder: float = 0.0
    wrist: float = 0.0
    lowerBack: float = 0.0
    eyes: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "neck": self.neck,
            "shoulder": self.shoulder,
            "wrist": self.wrist,
            "lowerBack": self.lowerBack,
            "eyes": self.eyes,
        }


@dataclass(frozen=True)
class ExerciseTypeDistribution:
    """운동 유형별 비율 (합계 ≈ 1.0)"""

    DURATION: float = 0.0
    REPS: float = 0.0
    EYES: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "DURATION": self.DURATION,
            "REPS": self.REPS,
            "EYES": self.EYES,
        }


@dataclass(frozen=True)
class DifficultyDistribution:
    """난이도별 완료 성공 비율"""

    level_1: float = 0.0
    level_2: float = 0.0
    level_3: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "1": self.level_1,
            "2": self.level_2,
            "3": self.level_3,
        }


@dataclass(frozen=True)
class ActivityLevel:
    """활동량 지표"""

    weekly_frequency: float = 0.0  # 최근 7일 세션 수

    def to_dict(self) -> dict[str, float]:
        return {"weekly_frequency": self.weekly_frequency}


@dataclass(frozen=True)
class UserActivityProfile:
    """
    사용자 활동 프로필 도메인 엔티티.

    - Qdrant payload로 직렬화 가능한 순수 데이터 객체
    - 외부 의존성(DB, 임베딩 모델) 없음
    - frozen=True: 생성 이후 불변, 동일 입력 → 동일 출력 보장
    """

    user_id: int
    preferred_body_parts: BodyPartDistribution
    preferred_exercise_types: ExerciseTypeDistribution
    preferred_difficulty: DifficultyDistribution
    activity_level: ActivityLevel

    def to_payload(self) -> dict:
        """Qdrant PointStruct.payload 직렬화"""
        return {
            "preferred_body_parts": self.preferred_body_parts.to_dict(),
            "preferred_exercise_types": self.preferred_exercise_types.to_dict(),
            "preferred_difficulty": self.preferred_difficulty.to_dict(),
            "activity_level": self.activity_level.to_dict(),
        }
