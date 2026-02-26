# app/api/v2/recommend.py
"""
V2 추천 API (비동기 콜백 + 폴링)
- POST /routines  : 추천 요청 접수 (202 즉시 반환)
- GET  /routines/{task_id} : 추천 상태 조회 (폴링)

교체 가능한 의존성 (get_* DI 함수만 수정하면 엔드포인트 코드 변경 불필요):
- TaskStore         : get_task_store()         → InMemoryTaskStore / RedisTaskStore
- TaskExecutor      : get_task_executor()      → BackgroundTaskExecutor / CeleryTaskExecutor
- ColdStartChecker  : get_cold_start_checker() → DefaultColdStartChecker / ActivityBasedColdStartChecker
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.configs.llm_config import llm_config
from app.core.config import settings
from app.core.exceptions import AppError
from app.data.loader import exercise_repository
from app.schemas.v2.request import UserInputV2
from app.schemas.v2.response import TaskAcceptedResponse, TaskResult
from app.services.callback_client import CallbackClient
from app.services.llm_clients.ollama_client import OllamaClient
from app.services.llm_clients.openai_client import OpenAIClient
from app.services.recommend.cold_start_checker import ColdStartChecker, DefaultColdStartChecker
from app.services.recommend.recommend_service import RecommendService
from app.services.response.v2 import V2ResponseBuilder
from app.services.task.executor import BackgroundTaskExecutor, TaskExecutor
from app.services.task.service import TaskService
from app.services.task.store import InMemoryTaskStore, TaskStore

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# 싱글톤 인스턴스
# ============================================================

# TODO: Task Store 교체: InMemoryTaskStore → RedisTaskStore(redis_client)
# TODO: Task Executor 교체: BackgroundTaskExecutor → CeleryTaskExecutor
_task_store: TaskStore = InMemoryTaskStore()
_callback_client = CallbackClient()
# TODO: Qdrant 연동 완료 후 ActivityBasedColdStartChecker 로 교체:
#   from app.services.user_activity.activity_service import UserActivityService
#   from app.services.recommend.cold_start_checker import ActivityBasedColdStartChecker
#   _cold_start_checker = ActivityBasedColdStartChecker(UserActivityService(...))
_cold_start_checker: ColdStartChecker = DefaultColdStartChecker()


def _create_recommend_service() -> RecommendService:
    """RecommendService 싱글톤 인스턴스 생성 (모듈 로드 시 1회)"""
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

    exercises = exercise_repository.raw_data
    return RecommendService(llm_client=llm_client, exercises=exercises, api_version="v2")


def _create_response_builder() -> V2ResponseBuilder:
    """V2ResponseBuilder 싱글톤 인스턴스 생성 (모듈 로드 시 1회)"""
    return V2ResponseBuilder(valid_exercise_ids=exercise_repository.exercise_ids)


_recommend_service = _create_recommend_service()
_response_builder = _create_response_builder()


# ============================================================
# 의존성 주입 함수 — 구현체 교체 지점
# ============================================================


def get_task_store() -> TaskStore:
    """
    TaskStore 의존성 주입
    """
    return _task_store


def get_cold_start_checker() -> ColdStartChecker:
    """
    ColdStartChecker 의존성 주입
    TODO: 사용자 프로필 기반 구현체로 교체 시 이 함수만 변경
    """
    return _cold_start_checker


def get_task_service(
    store: TaskStore = Depends(get_task_store),
) -> TaskService:
    """TaskService 의존성 주입"""
    return TaskService(
        store=store,
        recommend_service=_recommend_service,
        response_builder=_response_builder,
        callback_client=_callback_client,
        cold_start_checker=_cold_start_checker,
    )


def get_task_executor(
    background_tasks: BackgroundTasks,  # TODO: Task Executor 교체 시 제거
    task_service: TaskService = Depends(get_task_service),
) -> TaskExecutor:
    """
    TaskExecutor 의존성 주입
    TODO: Task Executor 교체 시 이 함수의 본문만 변경
    """
    return BackgroundTaskExecutor(background_tasks, task_service)


# ============================================================
# API Endpoints
# ============================================================


@router.post(
    "/routines",
    response_model=TaskAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_recommendation(
    user_input: UserInputV2,
    task_service: TaskService = Depends(get_task_service),
    executor: TaskExecutor = Depends(get_task_executor),
) -> TaskAcceptedResponse:
    """
    운동 루틴 추천 요청 접수 (V2:비동기)

    1. Task 생성 및 저장
    2. 백그라운드에서 추천 처리 시작
    3. taskId와 초기 상태 즉시 반환 (HTTP 202)

    의존성 Depnedency
    1. TaskService: Task 생명주기 관리 객체 (store, recommend_service, response_builder, callback_client)
    2. TaskExecutor: 백그라운드 태스크 실행 워커 (BackgroundTasks / Celery)
    """

    logger.info(
        "V2 추천 요청 수신: taskId=%s, userId=%d, routineCount=%d",
        user_input.taskId,
        user_input.userId,
        user_input.surveyData.routineCount,
    )

    try:
        task = task_service.create_task(user_input)
        executor.submit(task.task_id)
    except AppError:
        raise
    except Exception:
        logger.exception("추천 요청 처리 중 예기치 않은 오류 [taskId=%s]", user_input.taskId)
        raise

    return TaskAcceptedResponse(taskId=task.task_id, userId=task.user_id)


@router.get("/routines/{task_id}", response_model=TaskResult)
def get_recommendation_status(
    task_id: str,
    task_service: TaskService = Depends(get_task_service),
) -> TaskResult:
    """
    추천 태스크 상태 조회 (폴링)

    - IN_PROGRESS: 처리 중 (progress, currentStep 포함)
    - COMPLETED: 완료 (routines, summary 포함)
    - FAILED: 실패 (errorMessage 포함)
    """
    result = task_service.get_task_status(task_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task not found: {task_id}",
        )
    return result
