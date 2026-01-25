# uv run pytest -v tests/test_dataset.py

import json
import logging
from pathlib import Path
from typing import List

import pytest

from app.schemas.v1.exercise import DifficultyLevel, Exercise
from app.schemas.v1.request import SurveyAnswer, UserSurvey

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_DIR = Path("examples")
EXERCISES_FILE = DATA_DIR / "exercises.json"
USERS_FILE = DATA_DIR / "users.json"


class TestExerciseSchema:
    """Exercise 스키마 검증 테스트"""

    @pytest.fixture
    def exercises(self) -> List[dict]:
        return json.loads(EXERCISES_FILE.read_text(encoding="utf-8"))

    def test_exercises_file_exists(self):
        assert EXERCISES_FILE.exists(), f"{EXERCISES_FILE} not found"

    def test_exercises_is_non_empty_list(self, exercises: List[dict]):
        assert isinstance(exercises, list), "exercises.json must be a list"
        assert len(exercises) > 0, "exercises.json must not be empty"

    def test_all_exercises_schema_valid(self, exercises: List[dict]):
        for idx, data in enumerate(exercises):
            try:
                Exercise.model_validate(data)
            except Exception as e:
                pytest.fail(f"Exercise[{idx}] schema validation failed: {e}")

    def test_all_exercises_domain_valid(self, exercises: List[dict]):
        for idx, data in enumerate(exercises):
            exercise = Exercise.model_validate(data)
            assert exercise.difficulty in DifficultyLevel, (
                f"Exercise[{idx}] has invalid difficulty: {exercise.difficulty}"
            )
            assert exercise.tags.strip(), f"Exercise[{idx}] tags must not be empty"


class TestUserSurveySchema:
    """UserSurvey (request) 스키마 검증 테스트"""

    @pytest.fixture
    def users(self) -> List[dict]:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))

    def test_users_file_exists(self):
        assert USERS_FILE.exists(), f"{USERS_FILE} not found"

    def test_users_is_non_empty_list(self, users: List[dict]):
        assert isinstance(users, list), "users.json must be a list"
        assert len(users) > 0, "users.json must not be empty"

    def test_all_users_survey_schema_valid(self, users: List[dict]):
        for idx, data in enumerate(users):
            try:
                UserSurvey.model_validate(data)
            except Exception as e:
                pytest.fail(f"User[{idx}] schema validation failed: {e}")

    def test_all_survey_answers_schema_valid(self, users: List[dict]):
        for idx, data in enumerate(users):
            user_survey = UserSurvey.model_validate(data)
            for ans_idx, answer in enumerate(user_survey.survey):
                assert isinstance(answer, SurveyAnswer), (
                    f"User[{idx}].survey[{ans_idx}] is not SurveyAnswer"
                )

    def test_all_users_domain_valid(self, users: List[dict]):
        for idx, data in enumerate(users):
            user_survey = UserSurvey.model_validate(data)
            assert user_survey.routineCount >= 0, f"User[{idx}] routineCount must be >= 0"
            assert len(user_survey.survey) > 0, f"User[{idx}] survey must not be empty"
            for ans_idx, answer in enumerate(user_survey.survey):
                assert answer.questionContent.strip(), (
                    f"User[{idx}].survey[{ans_idx}] questionContent must not be empty"
                )
                assert answer.selectedOptionSortOrder >= 1, (
                    f"User[{idx}].survey[{ans_idx}] selectedOptionSortOrder must be >= 1"
                )
