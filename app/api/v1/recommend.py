# app/api/v1/recommend.py

"""
추천 API (v1)
- get_recommend_service(): RecommendService 의존성 주입
- get_response_builder(): V1ResponseBuilder 의존성 주입
- POST /routines: 운동 루틴 추천

Raise:

HTTP status:

"""

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends

from app.configs.llm_config import llm_config
from app.core.config import settings
from app.core.exceptions import (
    # DependencyNotReadyError,
    AppError,
)
from app.schemas.v1.request import UserInputV1
from app.schemas.v1.response import RecommendationResponseV1
from app.services.llm_clients.ollama_client import OllamaClient
from app.services.llm_clients.openai_client import OpenAIClient
from app.services.recommend.recommend_service import RecommendService
from app.services.response.v1 import V1ResponseBuilder

logger = logging.getLogger(__name__)

router = APIRouter()


def get_recommend_service() -> RecommendService:
    """
    추천 서비스 인스턴스 생성 : RecommendService 의존성 주입 함수

    운동 데이터는 _build_prompt() 호출 시 exercise_repository.raw_data를 동적 조회하므로
    /update/exercises 이후에도 항상 최신 데이터가 반영됨.
    """

    provider_name = llm_config.default_provider
    provider_config = llm_config.providers.get(provider_name)

    if provider_name == "openai":
        api_key = settings.OPENAI_API_KEY
        llm_client = OpenAIClient(
            api_key=api_key,  # type: ignore
            model=provider_config.model,  # type: ignore
            default_timeout=provider_config.timeout_sec,  # type: ignore
        )
    elif provider_name == "ollama_cloud":
        api_key = settings.OLLAMA_API_KEY
        llm_client = OllamaClient(
            api_key=api_key,  # type: ignore
            model=provider_config.model,  # type: ignore
            default_timeout=provider_config.timeout_sec,  # type: ignore
        )
    # elif provider_name == "gemini":
    #     llm_client = GeminiClient(api_key=$GEMINI_API_KEY, model=provider_config.model)

    return RecommendService(llm_client=llm_client)


def get_response_builder() -> V1ResponseBuilder:
    """
    응답 빌더 인스턴스 생성 : V1ResponseBuilder 의존성 주입 함수

    exercise data는 build_core() 호출 시 exercise_repository.get_all()로 동적 갱신됨.
    """
    return V1ResponseBuilder()


@router.post("/routines", response_model=RecommendationResponseV1)
def recommend(
    user_input: UserInputV1,
    service: RecommendService = Depends(get_recommend_service),
    builder: V1ResponseBuilder = Depends(get_response_builder),
) -> RecommendationResponseV1:
    """
    운동 루틴 추천 API (v1)

    사용자 설문 데이터를 기반으로 맞춤형 운동 루틴 추천

    Args:
    - user_input: 사용자 설문 데이터
    - service: 추천 서비스 (DI)
    - builder: 응답 빌더 (DI)

    Returns:
    - RecommendationResponseV1: 추천 결과 또는 에러 응답

    Dependency:
    - RecommendService
        - llm_client
        - exercises
    - V1ResponseBuilder
        - valid_exercise_ids
        - llm_client
    """
    logger.info("V1 추천 요청 수신: routineCount=%d", user_input.surveyData.routineCount)

    # taskId는 요청 진입 시점에 생성 (향후 비동기 처리 대비)
    task_id = uuid4().hex

    try:
        # 1. LLM 기반 추천 (또는 rule-based fallback)
        llm_output = service.recommend_routines(survey=user_input.surveyData)

        # 2. 유효성 검증 + 응답 생성
        return builder.build(llm_output, task_id=task_id, survey=user_input.surveyData)

    except AppError as e:
        logger.error("서비스 오류 [task_id=%s]: %s - %s", task_id, type(e).__name__, e)
        # Need a fallback builder for error response
        return builder.build_failed(task_id=task_id, error_message=str(e))
