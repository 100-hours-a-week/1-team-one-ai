# app/api/v1/recommend.py
"""
추천 API (v1) — router + endpoints only

DI 배선은 app/api/deps.py 참조.
- POST /routines: 설문 기반 운동 루틴 추천 (동기 응답)
"""

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends

from app.api.deps import get_recommend_service_v1, get_response_builder_v1
from app.core.exceptions import AppError
from app.schemas.v1.request import UserInputV1
from app.schemas.v1.response import RecommendationResponseV1
from app.services.recommend.recommend_service import RecommendService
from app.services.response.v1 import V1ResponseBuilder

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/routines", response_model=RecommendationResponseV1)
def recommend(
    user_input: UserInputV1,
    service: RecommendService = Depends(get_recommend_service_v1),
    builder: V1ResponseBuilder = Depends(get_response_builder_v1),
) -> RecommendationResponseV1:
    """
    운동 루틴 추천 API (v1)

    사용자 설문 데이터를 기반으로 맞춤형 운동 루틴 추천.

    Args:
    - user_input: 사용자 설문 데이터
    - service: 추천 서비스 (DI) → deps.get_recommend_service_v1
    - builder: 응답 빌더 (DI) → deps.get_response_builder_v1

    Returns:
    - RecommendationResponseV1: 추천 결과 또는 에러 응답 (항상 200)
    """
    logger.info("V1 추천 요청 수신: routineCount=%d", user_input.surveyData.routineCount)

    # taskId는 요청 진입 시점에 생성 (향후 비동기 처리 대비)
    task_id = uuid4().hex

    try:
        llm_output = service.recommend_routines(survey=user_input.surveyData)
        return builder.build(llm_output, task_id=task_id, survey=user_input.surveyData)

    except AppError as e:
        logger.error("서비스 오류 [task_id=%s]: %s - %s", task_id, type(e).__name__, e)
        return builder.build_failed(task_id=task_id, error_message=str(e))
