# tests/schemas/v1/test_schemas.py

"""
v1 스키마 정책 테스트 (request & response)

시나리오:
1. Request 검증 - 필드 범위 제약, extra 필드 금지
2. Response 비즈니스 규칙 - 타입별 필수 필드, 상태별 필수 필드
3. LLM 통합 - JSON 파싱 검증

uv run pytest -v tests/schemas/v1/test_schemas.py
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.v1.request import SurveyAnswer, UserInputV1, UserSurvey
from app.schemas.v1.response import (
    ExerciseType,
    LLMRoutineOutput,
    RecommendationResponseV1,
    RecommendationSummary,
    Routine,
    RoutineStep,
    TaskStatus,
)

# =============================================================================
# Request Schema - 입력 검증 정책
# =============================================================================


class TestRequestValidationPolicy:
    """
    Request 스키마 검증 정책
    - 사용자 입력값의 범위 제약
    - 허용되지 않은 필드 차단
    """

    def test_selected_option_sort_order_must_be_at_least_1(self) -> None:
        """설문 응답 순서는 1 이상이어야 한다 (1~5 척도 기반)."""
        with pytest.raises(ValidationError):
            SurveyAnswer(questionContent="질문", selectedOptionSortOrder=0)

    def test_routine_count_cannot_be_negative(self) -> None:
        """요청 루틴 개수는 음수가 될 수 없다."""
        with pytest.raises(ValidationError):
            UserSurvey(routineCount=-1, survey=[])

    def test_request_forbids_extra_fields(self) -> None:
        """API 요청에 정의되지 않은 필드가 있으면 거부한다 (보안)."""
        with pytest.raises(ValidationError):
            UserInputV1(
                surveyData=UserSurvey(routineCount=1, survey=[]),
                extraField="not allowed",  # type: ignore
            )


# =============================================================================
# Response Schema - 운동 타입별 비즈니스 규칙
# =============================================================================


class TestExerciseTypeRules:
    """
    운동 타입별 필수 필드 규칙
    - REPS: targetReps 필수, durationTime 불가
    - DURATION: durationTime 필수, targetReps 불가
    """

    def test_reps_exercise_requires_target_reps(self) -> None:
        """REPS 타입 운동은 targetReps가 필수이다."""
        with pytest.raises(ValidationError, match="targetReps가 필수"):
            RoutineStep(
                exerciseId="ex001",
                type=ExerciseType.REPS,
                stepOrder=1,
                limitTime=30,
                targetReps=None,
                durationTime=None,
            )

    def test_reps_exercise_forbids_duration_time(self) -> None:
        """REPS 타입 운동은 durationTime을 가질 수 없다."""
        with pytest.raises(ValidationError, match="durationTime을 가질 수 없"):
            RoutineStep(
                exerciseId="ex001",
                type=ExerciseType.REPS,
                stepOrder=1,
                limitTime=30,
                targetReps=10,
                durationTime=20,
            )

    def test_duration_exercise_requires_duration_time(self) -> None:
        """DURATION 타입 운동은 durationTime이 필수이다."""
        with pytest.raises(ValidationError, match="durationTime이 필수"):
            RoutineStep(
                exerciseId="ex001",
                type=ExerciseType.DURATION,
                stepOrder=1,
                limitTime=30,
                targetReps=None,
                durationTime=None,
            )

    def test_duration_exercise_forbids_target_reps(self) -> None:
        """DURATION 타입 운동은 targetReps를 가질 수 없다."""
        with pytest.raises(ValidationError, match="targetReps를 가질 수 없"):
            RoutineStep(
                exerciseId="ex001",
                type=ExerciseType.DURATION,
                stepOrder=1,
                limitTime=30,
                targetReps=10,
                durationTime=20,
            )


# =============================================================================
# Response Schema - 순서/개수 제약
# =============================================================================


class TestOrderConstraints:
    """
    순서 필드 제약
    - stepOrder, routineOrder는 1부터 시작
    - 루틴은 최소 1개 이상의 step 필요
    """

    def test_step_order_must_start_from_1(self) -> None:
        """stepOrder는 1 이상이어야 한다."""
        with pytest.raises(ValidationError):
            RoutineStep(
                exerciseId="ex001",
                type=ExerciseType.REPS,
                stepOrder=0,
                limitTime=30,
                targetReps=10,
                durationTime=None,
            )

    def test_routine_order_must_start_from_1(self) -> None:
        """routineOrder는 1 이상이어야 한다."""
        with pytest.raises(ValidationError):
            Routine(routineOrder=0, reason="test", steps=[])

    def test_routine_must_have_at_least_one_step(self) -> None:
        """루틴은 최소 1개 이상의 step을 포함해야 한다."""
        with pytest.raises(ValidationError, match="최소 1개 이상"):
            Routine(routineOrder=1, reason="빈 루틴", steps=[])


# =============================================================================
# Response Schema - 상태별 필수 필드
# =============================================================================


class TestResponseStatusRules:
    """
    응답 상태별 필수 필드 규칙
    - COMPLETED: summary, routines 필수
    """

    @pytest.fixture
    def sample_routine(self) -> Routine:
        """테스트용 루틴 데이터."""
        return Routine(
            routineOrder=1,
            reason="테스트 루틴",
            steps=[
                RoutineStep(
                    exerciseId="ex001",
                    type=ExerciseType.REPS,
                    stepOrder=1,
                    limitTime=30,
                    targetReps=10,
                    durationTime=None,
                )
            ],
        )

    def test_completed_status_requires_summary(self, sample_routine: Routine) -> None:
        """COMPLETED 상태에서는 summary가 필수이다."""
        with pytest.raises(ValidationError, match="summary가 필수"):
            RecommendationResponseV1(
                taskId="task-123",
                status=TaskStatus.COMPLETED,
                progress=100,
                currentStep="완료",
                summary=None,
                routines=[sample_routine],
                completedAt=datetime.now(UTC),
                errorMessage=None,
            )

    def test_completed_status_requires_routines(self) -> None:
        """COMPLETED 상태에서는 routines가 필수이다."""
        with pytest.raises(ValidationError, match="routines가 필수"):
            RecommendationResponseV1(
                taskId="task-123",
                status=TaskStatus.COMPLETED,
                progress=100,
                currentStep="완료",
                summary=RecommendationSummary(totalRoutines=1, totalExercises=3),
                routines=None,
                completedAt=datetime.now(UTC),
                errorMessage=None,
            )

    def test_response_forbids_extra_fields(self) -> None:
        """API 응답에 정의되지 않은 필드가 있으면 거부한다."""
        with pytest.raises(ValidationError):
            RecommendationResponseV1(
                taskId="task-123",
                status=TaskStatus.IN_PROGRESS,
                progress=60,
                currentStep="진행 중",
                summary=None,
                routines=None,
                completedAt=None,
                errorMessage=None,
                extraField="not allowed",  # type: ignore
            )


# =============================================================================
# LLM 통합 - JSON 파싱
# =============================================================================


class TestLLMOutputParsing:
    """
    LLM JSON 출력 파싱 테스트
    - LLM이 반환하는 JSON을 Pydantic 모델로 변환
    """

    def test_parse_llm_json_output(self) -> None:
        """LLM이 반환하는 JSON 형식을 LLMRoutineOutput으로 파싱할 수 있다."""
        llm_response = {
            "routines": [
                {
                    "routineOrder": 1,
                    "reason": "목 통증 완화를 위한 스트레칭",
                    "steps": [
                        {
                            "exerciseId": "ex001",
                            "type": "DURATION",
                            "stepOrder": 1,
                            "limitTime": 60,
                            "durationTime": 30,
                            "targetReps": None,
                        },
                        {
                            "exerciseId": "ex002",
                            "type": "REPS",
                            "stepOrder": 2,
                            "limitTime": 45,
                            "durationTime": None,
                            "targetReps": 10,
                        },
                    ],
                }
            ]
        }

        output = LLMRoutineOutput.model_validate(llm_response)

        assert len(output.routines) == 1
        assert output.routines[0].reason == "목 통증 완화를 위한 스트레칭"
        assert len(output.routines[0].steps) == 2
        assert output.routines[0].steps[0].type == ExerciseType.DURATION
        assert output.routines[0].steps[1].type == ExerciseType.REPS
