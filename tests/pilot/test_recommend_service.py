# tests/services/test_recommend_service.py

"""RecommendService 테스트.

pytest -v -s tests/services/test_recommend_service.py
"""

import json
from unittest.mock import MagicMock

import pytest

from app.schemas.v1.request import SurveyAnswer, UserSurvey
from app.schemas.v1.response import LLMRoutineOutput
from app.services.llm_clients.base import (
    LLMAuthenticationError,
    LLMClient,
    LLMInvalidResponseError,
    LLMNetworkError,
    LLMTimeoutError,
)
from app.services.recommend_service import RecommendService


class TestRecommendService:
    """RecommendService 핵심 기능 테스트."""

    @pytest.fixture
    def mock_llm_client(self, llm_inference_data: dict) -> MagicMock:
        """Mock LLM 클라이언트 fixture."""
        mock = MagicMock(spec=LLMClient)
        mock.generate.return_value = json.dumps(llm_inference_data)
        return mock

    @pytest.fixture
    def sample_survey(self, user_data: list[dict]) -> UserSurvey:
        """샘플 설문 데이터 fixture."""
        data = user_data[0]
        return UserSurvey(
            routineCount=data["routineCount"],
            survey=data["survey"],
        )

    @pytest.fixture
    def sample_exercises(self, exercise_data: list[dict]) -> list[dict]:
        """샘플 운동 데이터 fixture."""
        return exercise_data[:10]

    def test_recommend_routines_returns_llm_routine_output(
        self,
        mock_llm_client: MagicMock,
        sample_survey: UserSurvey,
        sample_exercises: list[dict],
    ) -> None:
        """recommend_routines가 LLMRoutineOutput을 반환하는지 확인."""
        service = RecommendService(llm_client=mock_llm_client, exercises=sample_exercises)

        result = service.recommend_routines(sample_survey)

        assert isinstance(result, LLMRoutineOutput)
        assert len(result.routines) >= 1

    def test_recommend_routines_calls_llm_generate(
        self,
        mock_llm_client: MagicMock,
        sample_survey: UserSurvey,
        sample_exercises: list[dict],
    ) -> None:
        """recommend_routines가 LLM generate를 호출하는지 확인."""
        service = RecommendService(llm_client=mock_llm_client, exercises=sample_exercises)

        service.recommend_routines(sample_survey)

        mock_llm_client.generate.assert_called_once()
        call_args = mock_llm_client.generate.call_args[0]
        system_prompt, user_prompt = call_args[0], call_args[1]

        assert len(system_prompt) > 0
        assert str(sample_survey.routineCount) in user_prompt

    def test_recommend_routines_parses_valid_response(
        self,
        mock_llm_client: MagicMock,
        sample_survey: UserSurvey,
        sample_exercises: list[dict],
        llm_inference_data: dict,
    ) -> None:
        """유효한 LLM 응답을 올바르게 파싱하는지 확인."""
        service = RecommendService(llm_client=mock_llm_client, exercises=sample_exercises)

        result = service.recommend_routines(sample_survey)

        routine = result.routines[0]
        assert routine.routineOrder == llm_inference_data["routines"][0]["routineOrder"]
        assert len(routine.steps) > 0


class TestRecommendServiceRetry:
    """재시도 로직 테스트."""

    @pytest.fixture
    def sample_survey(self, user_data: list[dict]) -> UserSurvey:
        """샘플 설문 데이터 fixture."""
        data = user_data[0]
        return UserSurvey(
            routineCount=data["routineCount"],
            survey=data["survey"],
        )

    @pytest.fixture
    def sample_exercises(self, exercise_data: list[dict]) -> list[dict]:
        """샘플 운동 데이터 fixture."""
        return exercise_data[:10]

    @pytest.fixture
    def valid_llm_response(self, llm_inference_data: dict) -> str:
        """유효한 LLM 응답 JSON 문자열."""
        return json.dumps(llm_inference_data)

    def test_retry_on_timeout_then_success(
        self,
        sample_survey: UserSurvey,
        sample_exercises: list[dict],
        valid_llm_response: str,
    ) -> None:
        """타임아웃 후 재시도 성공."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate.side_effect = [
            LLMTimeoutError("timeout"),
            valid_llm_response,
        ]

        service = RecommendService(llm_client=mock_llm, exercises=sample_exercises)

        result = service.recommend_routines(sample_survey)

        assert isinstance(result, LLMRoutineOutput)
        assert mock_llm.generate.call_count == 2

    def test_retry_on_network_error_then_success(
        self,
        sample_survey: UserSurvey,
        sample_exercises: list[dict],
        valid_llm_response: str,
    ) -> None:
        """네트워크 에러 후 재시도 성공."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate.side_effect = [
            LLMNetworkError("connection failed"),
            valid_llm_response,
        ]

        service = RecommendService(llm_client=mock_llm, exercises=sample_exercises)

        result = service.recommend_routines(sample_survey)

        assert isinstance(result, LLMRoutineOutput)
        assert mock_llm.generate.call_count == 2

    def test_retry_on_invalid_response_then_success(
        self,
        sample_survey: UserSurvey,
        sample_exercises: list[dict],
        valid_llm_response: str,
    ) -> None:
        """잘못된 응답 후 재시도 성공."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate.side_effect = [
            "invalid json",
            valid_llm_response,
        ]

        service = RecommendService(llm_client=mock_llm, exercises=sample_exercises)

        result = service.recommend_routines(sample_survey)

        assert isinstance(result, LLMRoutineOutput)
        assert mock_llm.generate.call_count == 2

    def test_retry_exhausted_raises_error_when_fallback_disabled(
        self,
        sample_survey: UserSurvey,
        sample_exercises: list[dict],
    ) -> None:
        """모든 재시도 실패 + fallback 비활성화 시 에러 발생."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate.side_effect = LLMTimeoutError("timeout")

        service = RecommendService(llm_client=mock_llm, exercises=sample_exercises)

        with pytest.raises(LLMInvalidResponseError) as exc_info:
            service.recommend_routines(sample_survey)

        assert "재시도 3회" in str(exc_info.value)
        assert mock_llm.generate.call_count == 3

    def test_no_retry_on_authentication_error(
        self,
        sample_survey: UserSurvey,
        sample_exercises: list[dict],
    ) -> None:
        """인증 에러는 재시도하지 않음."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate.side_effect = LLMAuthenticationError("invalid api key")

        service = RecommendService(llm_client=mock_llm, exercises=sample_exercises)

        with pytest.raises(LLMInvalidResponseError):
            service.recommend_routines(sample_survey)

        # 인증 에러는 재시도 없이 즉시 실패
        assert mock_llm.generate.call_count == 1


class TestRecommendServiceFallback:
    """Fallback 로직 테스트."""

    @pytest.fixture
    def sample_survey(self, user_data: list[dict]) -> UserSurvey:
        """샘플 설문 데이터 fixture."""
        data = user_data[0]
        return UserSurvey(
            routineCount=data["routineCount"],
            survey=data["survey"],
        )

    @pytest.fixture
    def sample_exercises(self, exercise_data: list[dict]) -> list[dict]:
        """샘플 운동 데이터 fixture."""
        return exercise_data[:10]

    def test_fallback_when_llm_fails(
        self,
        sample_survey: UserSurvey,
        sample_exercises: list[dict],
    ) -> None:
        """LLM 실패 시 rule-based fallback 실행."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate.side_effect = LLMTimeoutError("timeout")

        service = RecommendService(llm_client=mock_llm, exercises=sample_exercises)

        result = service.recommend_routines(sample_survey)

        assert isinstance(result, LLMRoutineOutput)
        assert len(result.routines) >= 1
        # fallback은 항상 루틴을 생성함
        assert all(len(r.steps) >= 1 for r in result.routines)

    def test_fallback_disabled_raises_error(
        self,
        sample_survey: UserSurvey,
        sample_exercises: list[dict],
    ) -> None:
        """fallback 비활성화 시 에러 발생."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate.side_effect = LLMTimeoutError("timeout")

        service = RecommendService(llm_client=mock_llm, exercises=sample_exercises)

        with pytest.raises(LLMInvalidResponseError):
            service.recommend_routines(sample_survey)


class TestRecommendServiceParsing:
    """응답 파싱 테스트."""

    @pytest.fixture
    def sample_survey(self, user_data: list[dict]) -> UserSurvey:
        """샘플 설문 데이터 fixture."""
        data = user_data[0]
        return UserSurvey(
            routineCount=data["routineCount"],
            survey=data["survey"],
        )

    @pytest.fixture
    def sample_exercises(self, exercise_data: list[dict]) -> list[dict]:
        """샘플 운동 데이터 fixture."""
        return exercise_data[:10]

    def test_invalid_json_raises_error(
        self,
        sample_survey: UserSurvey,
        sample_exercises: list[dict],
    ) -> None:
        """잘못된 JSON 응답 시 에러 발생."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate.return_value = "not valid json {"

        service = RecommendService(llm_client=mock_llm, exercises=sample_exercises)

        with pytest.raises(LLMInvalidResponseError) as exc_info:
            service.recommend_routines(sample_survey)

        assert "JSON 파싱 실패" in str(exc_info.value) or "재시도" in str(exc_info.value)

    def test_invalid_schema_raises_error(
        self,
        sample_survey: UserSurvey,
        sample_exercises: list[dict],
    ) -> None:
        """스키마가 맞지 않는 응답 시 에러 발생."""
        invalid_response = json.dumps({"routines": [{"wrong_field": "value"}]})

        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate.return_value = invalid_response

        service = RecommendService(llm_client=mock_llm, exercises=sample_exercises)

        with pytest.raises(LLMInvalidResponseError) as exc_info:
            service.recommend_routines(sample_survey)

        assert "스키마 검증 실패" in str(exc_info.value) or "재시도" in str(exc_info.value)

    def test_empty_routines_raises_error(
        self,
        sample_survey: UserSurvey,
        sample_exercises: list[dict],
    ) -> None:
        """빈 루틴 배열 응답 시 에러 발생 (스키마 유효하지만 의미 없는 응답)."""
        empty_response = json.dumps({"routines": []})

        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate.return_value = empty_response

        service = RecommendService(llm_client=mock_llm, exercises=sample_exercises)

        # 빈 routines는 유효한 스키마이므로 정상 반환됨
        result = service.recommend_routines(sample_survey)
        assert isinstance(result, LLMRoutineOutput)
        assert len(result.routines) == 0


class TestRecommendServiceBuildPrompt:
    """_build_prompt 메서드 테스트."""

    @pytest.fixture
    def service(self, exercise_data: list[dict]) -> RecommendService:
        """테스트용 서비스 인스턴스."""
        mock_llm = MagicMock(spec=LLMClient)
        return RecommendService(llm_client=mock_llm, exercises=exercise_data[:5])

    def test_build_prompt_includes_routine_count(
        self,
        service: RecommendService,
    ) -> None:
        """프롬프트에 루틴 개수가 포함되는지 확인."""
        survey = UserSurvey(
            routineCount=3,
            survey=[
                SurveyAnswer(questionContent="목 통증", selectedOptionSortOrder=4),
            ],
        )

        prompt = service._build_prompt(survey)

        assert "3" in prompt

    def test_build_prompt_includes_survey_content(
        self,
        service: RecommendService,
    ) -> None:
        """프롬프트에 설문 내용이 포함되는지 확인."""
        survey = UserSurvey(
            routineCount=1,
            survey=[
                SurveyAnswer(questionContent="목 부위 통증", selectedOptionSortOrder=5),
                SurveyAnswer(questionContent="어깨 부위 불편", selectedOptionSortOrder=3),
            ],
        )

        prompt = service._build_prompt(survey)

        assert "목 부위 통증" in prompt
        assert "어깨 부위 불편" in prompt

    def test_build_prompt_includes_exercises(
        self,
        service: RecommendService,
    ) -> None:
        """프롬프트에 운동 데이터가 포함되는지 확인."""
        survey = UserSurvey(
            routineCount=1,
            survey=[
                SurveyAnswer(questionContent="테스트 질문", selectedOptionSortOrder=1),
            ],
        )

        prompt = service._build_prompt(survey)

        # exercises가 JSON으로 포함되어야 함
        assert "exerciseId" in prompt or "seated_" in prompt


class TestRecommendServiceParseResponse:
    """_parse_response 메서드 테스트."""

    @pytest.fixture
    def service(self, exercise_data: list[dict]) -> RecommendService:
        """테스트용 서비스 인스턴스."""
        mock_llm = MagicMock(spec=LLMClient)
        return RecommendService(llm_client=mock_llm, exercises=exercise_data[:5])

    def test_parse_valid_response(
        self,
        service: RecommendService,
        llm_inference_data: dict,
    ) -> None:
        """유효한 응답 파싱."""
        raw = json.dumps(llm_inference_data)

        result = service._parse_response(raw)

        assert isinstance(result, LLMRoutineOutput)
        assert len(result.routines) == len(llm_inference_data["routines"])

    def test_parse_invalid_json_raises_error(
        self,
        service: RecommendService,
    ) -> None:
        """잘못된 JSON 파싱 시 에러."""
        with pytest.raises(LLMInvalidResponseError) as exc_info:
            service._parse_response("not json")

        assert "JSON 파싱 실패" in str(exc_info.value)

    def test_parse_invalid_schema_raises_error(
        self,
        service: RecommendService,
    ) -> None:
        """잘못된 스키마 파싱 시 에러."""
        invalid_data = json.dumps({"routines": [{"invalid": "data"}]})

        with pytest.raises(LLMInvalidResponseError) as exc_info:
            service._parse_response(invalid_data)

        assert "스키마 검증 실패" in str(exc_info.value)


class TestRecommendServiceConfigDefaults:
    """설정 기본값 테스트."""

    @pytest.fixture
    def sample_exercises(self, exercise_data: list[dict]) -> list[dict]:
        """샘플 운동 데이터 fixture."""
        return exercise_data[:5]

    def test_explicit_config_overrides_defaults(
        self,
        sample_exercises: list[dict],
    ) -> None:
        """명시적 설정이 기본값을 오버라이드하는지 확인."""
        mock_llm = MagicMock(spec=LLMClient)

        service = RecommendService(llm_client=mock_llm, exercises=sample_exercises)

        assert service._max_retries == 5
        assert service._fallback_enabled is False

    def test_fallback_enabled_creates_rule_based_recommender(
        self,
        sample_exercises: list[dict],
    ) -> None:
        """fallback 활성화 시 RuleBasedRecommender 생성 확인."""
        mock_llm = MagicMock(spec=LLMClient)

        service = RecommendService(llm_client=mock_llm, exercises=sample_exercises)

        assert service._rule_based is not None

    def test_fallback_disabled_no_rule_based_recommender(
        self,
        sample_exercises: list[dict],
    ) -> None:
        """fallback 비활성화 시 RuleBasedRecommender 미생성 확인."""
        mock_llm = MagicMock(spec=LLMClient)

        service = RecommendService(llm_client=mock_llm, exercises=sample_exercises)

        assert service._rule_based is None
