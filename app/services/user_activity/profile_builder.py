# app/services/user_activity/profile_builder.py
"""
사용자 활동 프로필 빌더

UserActivityProfileBuilder
- build(api_response) → UserActivityProfile
- to_passage(profile) → str  (임베딩용 자연어 문장)
"""

from __future__ import annotations

import warnings
from datetime import datetime, timedelta

import pandas as pd

from app.domain.user_activity import (
    ActivityLevel,
    BodyPartDistribution,
    DifficultyDistribution,
    ExerciseTypeDistribution,
    UserActivityProfile,
)
from app.schemas.v2.user_activity import UserActivityApiResponse

# ── 상수 ─────────────────────────────────────────────────────────────────────

ALL_BODY_PARTS = ["neck", "shoulder", "wrist", "lowerBack", "eyes"]
ALL_TYPES = ["DURATION", "REPS", "EYES"]
ALL_DIFFICULTIES = [1, 2, 3]
WEEKLY_WINDOW = 7   # 활동량 집계 기준일
MIN_RATIO = 0.1     # passage 생성 시 포함할 최소 비율 임계값


# ── ProfileBuilder ────────────────────────────────────────────────────────────


class UserActivityProfileBuilder:
    """
    UserActivityApiResponse → UserActivityProfile 변환기.

    Args:
        exercises: exercise_repository.raw_data (LLM 프롬프트용 dict 리스트).
                   bodyPart / type / difficulty 조인에 사용합니다.

    Methods:
        build()      : 구조화된 프로필 엔티티 생성
        to_passage() : 임베딩용 자연어 문장 생성
    """

    def __init__(self, exercises: list[dict]) -> None:
        # id 기준으로 조회 가능한 DataFrame으로 변환 (merge 시 재사용)
        self._exercises_df = pd.DataFrame(exercises)[
            ["id", "bodyPart", "type", "difficulty"]
        ]

    # ── public ────────────────────────────────────────────────────────────────

    def build(self, api_response: UserActivityApiResponse) -> UserActivityProfile:
        merged = self._merge(api_response)

        return UserActivityProfile(
            user_id=api_response.userId,
            preferred_body_parts=self._body_part_distribution(merged),
            preferred_exercise_types=self._type_distribution(merged),
            preferred_difficulty=self._difficulty_distribution(merged),
            activity_level=self._activity_level(
                api_response.userId,
                pd.DataFrame([s.model_dump() for s in api_response.exerciseSessions]),
            ),
        )

    def to_passage(self, profile: UserActivityProfile) -> str:
        """
        구조화된 프로필 → 임베딩용 자연어 passage.

        설문 query와 동일한 의미 공간에 사영되도록 동일한 prefix(passage:)를 사용합니다.
        MIN_RATIO 미만 항목은 노이즈로 간주하여 제외합니다.
        """
        bp = profile.preferred_body_parts.to_dict()
        et = profile.preferred_exercise_types.to_dict()
        pd_ = profile.preferred_difficulty.to_dict()
        wf = profile.activity_level.weekly_frequency

        dominant_parts = [k for k, v in bp.items() if v >= MIN_RATIO]
        dominant_types = [k for k, v in et.items() if v >= MIN_RATIO]
        dominant_diffs = [k for k, v in pd_.items() if v >= MIN_RATIO]

        return (
            f"passage: "
            f"주요 운동 부위: {', '.join(dominant_parts)} | "
            f"선호 운동 유형: {', '.join(dominant_types)} | "
            f"적합 난이도: {', '.join(dominant_diffs)} | "
            f"주간 운동 빈도: {wf:.1f}회"
        )

    # ── private: 데이터 준비 ──────────────────────────────────────────────────

    def _merge(self, api_response: UserActivityApiResponse) -> pd.DataFrame:
        """
        exerciseResults
          ← (routine_step_id = routineSteps.id) → routineSteps
          ← (exercise_id = exercises.id)         → exercises (로컬 보유 데이터)

        exercises의 bodyPart / type / difficulty 가 분포 계산에 필요합니다.
        """
        results_df = pd.DataFrame([r.model_dump() for r in api_response.exerciseResults])
        steps_df = pd.DataFrame([s.model_dump() for s in api_response.routineSteps])

        # 1단계: results ← steps
        merged = results_df.merge(
            steps_df,
            left_on="routine_step_id",
            right_on="id",
            suffixes=("", "_step"),
        )
        self._warn_missing_steps(results_df, merged)

        # 2단계: merged ← exercises (bodyPart, type, difficulty 획득)
        merged = merged.merge(
            self._exercises_df,
            left_on="exercise_id",
            right_on="id",
            suffixes=("", "_ex"),
        )
        self._warn_missing_exercises(steps_df, merged)

        return merged

    @staticmethod
    def _warn_missing_steps(
        results_df: pd.DataFrame,
        merged: pd.DataFrame,
    ) -> None:
        """merge 후 누락된 routine_step_id 경고 (silently drop 방지)."""
        original_ids = set(results_df["routine_step_id"].unique())
        merged_ids = set(merged["routine_step_id"].unique())
        missing = original_ids - merged_ids
        if missing:
            warnings.warn(
                f"[ProfileBuilder] routineSteps 누락 ids: {missing}. "
                "해당 운동 결과는 프로필 산출에서 제외됩니다.",
                stacklevel=3,
            )

    @staticmethod
    def _warn_missing_exercises(
        steps_df: pd.DataFrame,
        merged: pd.DataFrame,
    ) -> None:
        """merge 후 누락된 exercise_id 경고 (exercises.json 불일치 방지)."""
        original_ids = set(steps_df["exercise_id"].unique())
        merged_ids = set(merged["exercise_id"].unique())
        missing = original_ids - merged_ids
        if missing:
            warnings.warn(
                f"[ProfileBuilder] exercises 누락 ids: {missing}. "
                "exercises.json과 coreBE 데이터가 불일치합니다.",
                stacklevel=3,
            )

    # ── private: 분포 계산 ────────────────────────────────────────────────────

    @staticmethod
    def _body_part_distribution(merged: pd.DataFrame) -> BodyPartDistribution:
        counts = merged["bodyPart"].value_counts(normalize=True).to_dict()
        return BodyPartDistribution(
            **{part: round(counts.get(part, 0.0), 2) for part in ALL_BODY_PARTS}
        )

    @staticmethod
    def _type_distribution(merged: pd.DataFrame) -> ExerciseTypeDistribution:
        counts = merged["type"].value_counts(normalize=True).to_dict()
        return ExerciseTypeDistribution(**{t: round(counts.get(t, 0.0), 2) for t in ALL_TYPES})

    @staticmethod
    def _difficulty_distribution(merged: pd.DataFrame) -> DifficultyDistribution:
        success_by_diff = (
            merged.groupby("difficulty")
            .apply(lambda x: (x["status"] == "COMPLETED").sum() / len(x))
            .to_dict()
        )
        level_1, level_2, level_3 = (
            round(success_by_diff.get(d, 0.0), 2) for d in ALL_DIFFICULTIES
        )
        return DifficultyDistribution(
            level_1=level_1,
            level_2=level_2,
            level_3=level_3,
        )

    @staticmethod
    def _activity_level(
        user_id: int,
        sessions_df: pd.DataFrame,
    ) -> ActivityLevel:
        sessions_df["created_at"] = pd.to_datetime(sessions_df["created_at"])
        cutoff = datetime.now() - timedelta(days=WEEKLY_WINDOW)

        weekly_sessions = sessions_df[
            (sessions_df["user_id"] == user_id) & (sessions_df["created_at"] >= cutoff)
        ]
        return ActivityLevel(weekly_frequency=float(len(weekly_sessions["id"].unique())))
