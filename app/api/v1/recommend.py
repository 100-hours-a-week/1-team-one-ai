# app/api/v1/recommend.py
from fastapi import APIRouter

from app.schemas.v1.request import UserInputV1
from app.schemas.v1.response import (
    PROGRESS_STEP_PERCENTAGE,
    ProgressStep,
    RecommendationResponseV1,
    TaskStatus,
)

router = APIRouter()


@router.post("/routines", response_model=RecommendationResponseV1)
async def recommend(user_input: UserInputV1) -> RecommendationResponseV1:
    """
    운동 루틴 추천 API (v1)

    사용자 설문 데이터를 기반으로 맞춤형 운동 루틴을 추천합니다.
    """
    # TODO: 실제 추천 로직 구현 (recommend_service 연동)
    # 예시:
    # service = RecommendService(llm_client=commercial_client)
    # result = await service.generate_routines(user_input)
    # return RecommendationResponseV1(
    #     taskId=result.task_id,
    #     status=TaskStatus.COMPLETED,
    #     progress=PROGRESS_STEP_PERCENTAGE[ProgressStep.COMPLETED],
    #     currentStep=ProgressStep.COMPLETED.value,
    #     summary=RecommendationSummary(
    #         totalRoutines=len(result.routines),
    #         totalExercises=sum(len(r.steps) for r in result.routines),
    #     ),
    #     completedAt=datetime.now(UTC),
    #     routines=result.routines,
    # )
    return RecommendationResponseV1(
        taskId="placeholder-task-id",
        status=TaskStatus.IN_PROGRESS,
        progress=PROGRESS_STEP_PERCENTAGE[ProgressStep.LLM_INFERENCE],
        currentStep=ProgressStep.LLM_INFERENCE.value,
        summary=None,
        errorMessage=None,
        completedAt=None,
        routines=None,
    )
