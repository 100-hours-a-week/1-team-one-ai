# app/schemas/v2/user_activity.py
"""
coreBE로부터 받는 API response body 스키마
UserActivityApiResponse (exerciseResults, routineSteps, exerciseSessions)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

# ── exercise_results ────────────────────────────────────────────────────────


class ExerciseResultItem(BaseModel):
    id: int
    exercise_session_id: int
    routine_step_id: int
    status: str  # "COMPLETED" | "SKIPPED" | ...
    accuracy: Optional[int] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# ── routine_steps ────────────────────────────────────────────────────────────


class RoutineStepItem(BaseModel):
    id: int
    routine_id: int
    exercise_id: int
    target_reps: Optional[int] = None
    duration_time: Optional[int] = None
    limit_time: int
    step_order: int
    created_at: datetime


# ── exercise_sessions ────────────────────────────────────────────────────────


class ExerciseSessionItem(BaseModel):
    id: int
    user_id: int
    routine_id: int
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    is_routine_completed: bool
    created_at: datetime
    updated_at: datetime


# ── 최상위 response body ──────────────────────────────────────────────────────


class UserActivityApiResponse(BaseModel):
    userId: int
    exerciseResults: list[ExerciseResultItem]
    routineSteps: list[RoutineStepItem]
    exerciseSessions: list[ExerciseSessionItem]
