# tests/api/v1/test_recommend.py

"""
추천 API 엔드포인트 테스트

시나리오:
1. 요청 검증 - 필수 필드 누락, 잘못된 값 → 422
2. 정상 요청 - Mock 서비스로 응답 구조 검증 → 200
3. 에러 처리 - LLM 에러, 검증 에러 → 적절한 에러 응답

uv run pytest -v tests/api/v1/test_recommend.py
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.v1.recommend import get_recommend_service, get_response_builder
from app.main import app
from app.schemas.common import ExerciseType
from app.schemas.v1.response import (
    LLMRoutineOutput,
    Routine,
    RoutineStep,
    TaskStatus,
)
from app.services.llm_clients.base import LLMInvalidResponseError
from app.services.response_builder import ResponseBuilder, RoutineValidationError


@pytest.fixture
def test_client() -> TestClient:
    """테스트용 클라이언트."""
    return TestClient(app, raise_server_exceptions=False)


class TestRequestValidation:
    """
    요청 검증 테스트
    - API 계약(스키마)을 위반하는 요청은 422를 반환해야 한다
    """

    def test_missing_survey_data_returns_422(self, test_client: TestClient) -> None:
        """surveyData 필드 누락 시 422 반환."""
        response = test_client.post("/api/v1/routines", json={})

        assert response.status_code == 422

    def test_missing_routine_count_returns_422(self, test_client: TestClient) -> None:
        """routineCount 필드 누락 시 422 반환."""
        request_body = {
            "surveyData": {
                "survey": [],
            }
        }

        response = test_client.post("/api/v1/routines", json=request_body)

        assert response.status_code == 422

    def test_negative_routine_count_returns_422(self, test_client: TestClient) -> None:
        """routineCount가 음수일 때 422 반환."""
        request_body = {
            "surveyData": {
                "routineCount": -1,
                "survey": [],
            }
        }

        response = test_client.post("/api/v1/routines", json=request_body)

        assert response.status_code == 422

    def test_invalid_selected_option_sort_order_returns_422(self, test_client: TestClient) -> None:
        """selectedOptionSortOrder가 범위(1~)를 벗어나면 422 반환."""
        request_body = {
            "surveyData": {
                "routineCount": 1,
                "survey": [
                    {"questionContent": "질문", "selectedOptionSortOrder": 0},
                ],
            }
        }

        response = test_client.post("/api/v1/routines", json=request_body)

        assert response.status_code == 422

    def test_missing_question_content_returns_422(self, test_client: TestClient) -> None:
        """questionContent 필드 누락 시 422 반환."""
        request_body = {
            "surveyData": {
                "routineCount": 1,
                "survey": [
                    {"selectedOptionSortOrder": 3},
                ],
            }
        }

        response = test_client.post("/api/v1/routines", json=request_body)

        assert response.status_code == 422

    def test_extra_fields_returns_422(self, test_client: TestClient) -> None:
        """허용되지 않은 추가 필드가 있을 때 422 반환."""
        request_body = {
            "surveyData": {
                "routineCount": 1,
                "survey": [],
            },
            "extraField": "not allowed",
        }

        response = test_client.post("/api/v1/routines", json=request_body)

        assert response.status_code == 422


class TestRecommendEndpoint:
    """
    추천 API 정상 동작 테스트
    - 유효한 요청 시 올바른 응답 구조를 반환해야 한다
    """

    @pytest.fixture
    def mock_llm_output(self) -> LLMRoutineOutput:
        """Mock LLM 출력 데이터."""
        return LLMRoutineOutput(
            routines=[
                Routine(
                    routineOrder=1,
                    reason="목 통증 완화를 위한 스트레칭 루틴",
                    steps=[
                        RoutineStep(
                            exerciseId="seated_001",
                            type=ExerciseType.DURATION,
                            stepOrder=1,
                            limitTime=60,
                            durationTime=30,
                            targetReps=None,
                        ),
                        RoutineStep(
                            exerciseId="seated_005",
                            type=ExerciseType.REPS,
                            stepOrder=2,
                            limitTime=45,
                            durationTime=None,
                            targetReps=10,
                        ),
                    ],
                )
            ]
        )

    @pytest.fixture
    def valid_request_body(self) -> dict:
        """유효한 요청 데이터."""
        return {
            "surveyData": {
                "routineCount": 1,
                "survey": [
                    {"questionContent": "목 통증 정도", "selectedOptionSortOrder": 4},
                    {"questionContent": "어깨 통증 정도", "selectedOptionSortOrder": 3},
                ],
            }
        }

    @pytest.fixture
    def mock_response_builder(self) -> ResponseBuilder:
        """Mock ResponseBuilder (exerciseId 검증 비활성화)."""
        return ResponseBuilder(valid_exercise_ids=None)

    def test_valid_request_returns_200_with_routines(
        self,
        test_client: TestClient,
        mock_llm_output: LLMRoutineOutput,
        valid_request_body: dict,
        mock_response_builder: ResponseBuilder,
    ) -> None:
        """유효한 요청 시 200과 루틴 데이터를 반환한다."""
        mock_service = MagicMock()
        mock_service.recommend_routines.return_value = mock_llm_output

        app.dependency_overrides[get_recommend_service] = lambda: mock_service
        app.dependency_overrides[get_response_builder] = lambda: mock_response_builder

        try:
            response = test_client.post("/api/v1/routines", json=valid_request_body)

            assert response.status_code == 200

            data = response.json()
            assert data["status"] == TaskStatus.COMPLETED.value
            assert data["progress"] == 100
            assert data["summary"]["totalRoutines"] == 1
            assert data["summary"]["totalExercises"] == 2
            assert len(data["routines"]) == 1
            assert data["routines"][0]["reason"] == "목 통증 완화를 위한 스트레칭 루틴"
            assert data["taskId"] is not None
            assert data["completedAt"] is not None
        finally:
            app.dependency_overrides.clear()

    def test_service_called_with_correct_survey_data(
        self,
        test_client: TestClient,
        mock_llm_output: LLMRoutineOutput,
        valid_request_body: dict,
        mock_response_builder: ResponseBuilder,
    ) -> None:
        """서비스가 올바른 설문 데이터로 호출되는지 확인."""
        mock_service = MagicMock()
        mock_service.recommend_routines.return_value = mock_llm_output

        app.dependency_overrides[get_recommend_service] = lambda: mock_service
        app.dependency_overrides[get_response_builder] = lambda: mock_response_builder

        try:
            test_client.post("/api/v1/routines", json=valid_request_body)

            mock_service.recommend_routines.assert_called_once()
            call_kwargs = mock_service.recommend_routines.call_args.kwargs
            survey = call_kwargs["survey"]

            assert survey.routineCount == 1
            assert len(survey.survey) == 2
        finally:
            app.dependency_overrides.clear()

    def test_multiple_routines_response(
        self,
        test_client: TestClient,
        mock_response_builder: ResponseBuilder,
    ) -> None:
        """여러 루틴 요청 시 올바른 응답 반환."""
        multi_routine_output = LLMRoutineOutput(
            routines=[
                Routine(
                    routineOrder=1,
                    reason="첫 번째 루틴",
                    steps=[
                        RoutineStep(
                            exerciseId="seated_001",
                            type=ExerciseType.DURATION,
                            stepOrder=1,
                            limitTime=30,
                            durationTime=20,
                            targetReps=None,
                        ),
                    ],
                ),
                Routine(
                    routineOrder=2,
                    reason="두 번째 루틴",
                    steps=[
                        RoutineStep(
                            exerciseId="seated_005",
                            type=ExerciseType.REPS,
                            stepOrder=1,
                            limitTime=45,
                            durationTime=None,
                            targetReps=15,
                        ),
                    ],
                ),
            ]
        )

        mock_service = MagicMock()
        mock_service.recommend_routines.return_value = multi_routine_output

        app.dependency_overrides[get_recommend_service] = lambda: mock_service
        app.dependency_overrides[get_response_builder] = lambda: mock_response_builder

        request_body = {
            "surveyData": {
                "routineCount": 2,
                "survey": [
                    {"questionContent": "목 통증", "selectedOptionSortOrder": 3},
                ],
            }
        }

        try:
            response = test_client.post("/api/v1/routines", json=request_body)

            assert response.status_code == 200
            data = response.json()
            assert data["summary"]["totalRoutines"] == 2
            assert len(data["routines"]) == 2
        finally:
            app.dependency_overrides.clear()


class TestRecommendEndpointErrors:
    """
    추천 API 에러 처리 테스트
    - 서비스 에러 시 적절한 에러 응답을 반환해야 한다
    """

    @pytest.fixture
    def valid_request_body(self) -> dict:
        """유효한 요청 데이터."""
        return {
            "surveyData": {
                "routineCount": 1,
                "survey": [
                    {"questionContent": "목 통증", "selectedOptionSortOrder": 4},
                ],
            }
        }

    @pytest.fixture
    def mock_response_builder(self) -> ResponseBuilder:
        """Mock ResponseBuilder."""
        return ResponseBuilder(valid_exercise_ids=None)

    def test_llm_error_returns_failed_status(
        self,
        test_client: TestClient,
        valid_request_body: dict,
        mock_response_builder: ResponseBuilder,
    ) -> None:
        """LLM 에러 발생 시 FAILED 상태 응답."""
        mock_service = MagicMock()
        mock_service.recommend_routines.side_effect = LLMInvalidResponseError("LLM 응답 처리 실패")

        app.dependency_overrides[get_recommend_service] = lambda: mock_service
        app.dependency_overrides[get_response_builder] = lambda: mock_response_builder

        try:
            response = test_client.post("/api/v1/routines", json=valid_request_body)

            assert response.status_code == 200  # API는 200 반환, status 필드로 실패 표시
            data = response.json()
            assert data["status"] == TaskStatus.FAILED.value
            assert data["errorMessage"] is not None
            assert "LLM" in data["errorMessage"]
        finally:
            app.dependency_overrides.clear()

    def test_empty_routines_returns_failed_status(
        self,
        test_client: TestClient,
        valid_request_body: dict,
        mock_response_builder: ResponseBuilder,
    ) -> None:
        """빈 루틴 응답 시 FAILED 상태 응답."""
        empty_output = LLMRoutineOutput(routines=[])

        mock_service = MagicMock()
        mock_service.recommend_routines.return_value = empty_output

        app.dependency_overrides[get_recommend_service] = lambda: mock_service
        app.dependency_overrides[get_response_builder] = lambda: mock_response_builder

        try:
            response = test_client.post("/api/v1/routines", json=valid_request_body)

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == TaskStatus.FAILED.value
            assert "루틴" in data["errorMessage"]
        finally:
            app.dependency_overrides.clear()

    def test_routine_validation_error_returns_failed_status(
        self,
        test_client: TestClient,
        valid_request_body: dict,
    ) -> None:
        """루틴 검증 에러 발생 시 FAILED 상태 응답."""
        mock_service = MagicMock()
        mock_service.recommend_routines.return_value = LLMRoutineOutput(
            routines=[
                Routine(
                    routineOrder=1,
                    reason="테스트 루틴",
                    steps=[
                        RoutineStep(
                            exerciseId="valid_001",
                            type=ExerciseType.DURATION,
                            stepOrder=1,
                            limitTime=30,
                            durationTime=20,
                            targetReps=None,
                        ),
                    ],
                )
            ]
        )

        # ResponseBuilder가 RoutineValidationError를 발생시키도록 설정
        mock_builder = MagicMock()
        mock_builder.build.side_effect = RoutineValidationError("검증 실패")
        mock_builder.build_failed.return_value = ResponseBuilder(
            valid_exercise_ids=None
        ).build_failed(task_id="test", error_message="검증 실패")

        app.dependency_overrides[get_recommend_service] = lambda: mock_service
        app.dependency_overrides[get_response_builder] = lambda: mock_builder

        try:
            response = test_client.post("/api/v1/routines", json=valid_request_body)

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == TaskStatus.FAILED.value
        finally:
            app.dependency_overrides.clear()


class TestRecommendEndpointResponseStructure:
    """
    추천 API 응답 구조 테스트
    - 응답이 스키마에 맞는 구조를 가지는지 확인
    """

    @pytest.fixture
    def mock_llm_output(self) -> LLMRoutineOutput:
        """Mock LLM 출력 데이터."""
        return LLMRoutineOutput(
            routines=[
                Routine(
                    routineOrder=1,
                    reason="테스트 루틴",
                    steps=[
                        RoutineStep(
                            exerciseId="seated_001",
                            type=ExerciseType.DURATION,
                            stepOrder=1,
                            limitTime=30,
                            durationTime=20,
                            targetReps=None,
                        ),
                    ],
                )
            ]
        )

    @pytest.fixture
    def valid_request_body(self) -> dict:
        """유효한 요청 데이터."""
        return {
            "surveyData": {
                "routineCount": 1,
                "survey": [],
            }
        }

    @pytest.fixture
    def mock_response_builder(self) -> ResponseBuilder:
        """Mock ResponseBuilder."""
        return ResponseBuilder(valid_exercise_ids=None)

    def test_response_has_required_fields(
        self,
        test_client: TestClient,
        mock_llm_output: LLMRoutineOutput,
        valid_request_body: dict,
        mock_response_builder: ResponseBuilder,
    ) -> None:
        """응답에 필수 필드가 모두 존재하는지 확인."""
        mock_service = MagicMock()
        mock_service.recommend_routines.return_value = mock_llm_output

        app.dependency_overrides[get_recommend_service] = lambda: mock_service
        app.dependency_overrides[get_response_builder] = lambda: mock_response_builder

        try:
            response = test_client.post("/api/v1/routines", json=valid_request_body)

            data = response.json()

            # 필수 필드 확인
            assert "taskId" in data
            assert "status" in data
            assert "progress" in data
            assert "currentStep" in data
            assert "summary" in data
            assert "routines" in data
        finally:
            app.dependency_overrides.clear()

    def test_routine_step_has_required_fields(
        self,
        test_client: TestClient,
        mock_llm_output: LLMRoutineOutput,
        valid_request_body: dict,
        mock_response_builder: ResponseBuilder,
    ) -> None:
        """루틴 스텝에 필수 필드가 모두 존재하는지 확인."""
        mock_service = MagicMock()
        mock_service.recommend_routines.return_value = mock_llm_output

        app.dependency_overrides[get_recommend_service] = lambda: mock_service
        app.dependency_overrides[get_response_builder] = lambda: mock_response_builder

        try:
            response = test_client.post("/api/v1/routines", json=valid_request_body)

            data = response.json()
            step = data["routines"][0]["steps"][0]

            assert "exerciseId" in step
            assert "type" in step
            assert "stepOrder" in step
            assert "limitTime" in step
        finally:
            app.dependency_overrides.clear()

    def test_duration_type_step_has_duration_time(
        self,
        test_client: TestClient,
        mock_llm_output: LLMRoutineOutput,
        valid_request_body: dict,
        mock_response_builder: ResponseBuilder,
    ) -> None:
        """DURATION 타입 스텝에 durationTime이 존재하는지 확인."""
        mock_service = MagicMock()
        mock_service.recommend_routines.return_value = mock_llm_output

        app.dependency_overrides[get_recommend_service] = lambda: mock_service
        app.dependency_overrides[get_response_builder] = lambda: mock_response_builder

        try:
            response = test_client.post("/api/v1/routines", json=valid_request_body)

            data = response.json()
            step = data["routines"][0]["steps"][0]

            assert step["type"] == ExerciseType.DURATION.value
            assert step["durationTime"] is not None
            assert step["targetReps"] is None
        finally:
            app.dependency_overrides.clear()

    def test_reps_type_step_has_target_reps(
        self,
        test_client: TestClient,
        valid_request_body: dict,
        mock_response_builder: ResponseBuilder,
    ) -> None:
        """REPS 타입 스텝에 targetReps가 존재하는지 확인."""
        reps_output = LLMRoutineOutput(
            routines=[
                Routine(
                    routineOrder=1,
                    reason="테스트 루틴",
                    steps=[
                        RoutineStep(
                            exerciseId="seated_005",
                            type=ExerciseType.REPS,
                            stepOrder=1,
                            limitTime=45,
                            durationTime=None,
                            targetReps=10,
                        ),
                    ],
                )
            ]
        )

        mock_service = MagicMock()
        mock_service.recommend_routines.return_value = reps_output

        app.dependency_overrides[get_recommend_service] = lambda: mock_service
        app.dependency_overrides[get_response_builder] = lambda: mock_response_builder

        try:
            response = test_client.post("/api/v1/routines", json=valid_request_body)

            data = response.json()
            step = data["routines"][0]["steps"][0]

            assert step["type"] == ExerciseType.REPS.value
            assert step["targetReps"] is not None
            assert step["durationTime"] is None
        finally:
            app.dependency_overrides.clear()
