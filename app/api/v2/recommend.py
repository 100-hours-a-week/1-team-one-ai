# app/api/v2/recommend.py
"""
추천 API (v2) — router + endpoints only

DI 배선은 app/api/deps.py 참조.
구현체 교체 지점 (deps.py의 함수만 수정):
  - TaskStore        : get_task_store()         → InMemoryTaskStore / RedisTaskStore
  - TaskExecutor     : get_task_executor()      → BackgroundTaskExecutor / CeleryTaskExecutor
  - ColdStartChecker : get_cold_start_checker() → DefaultColdStartChecker / ActivityBasedColdStartChecker

추천 경로 (POST /routines):
  1. Qdrant 연결 성공 → VectorSearch 경로 (submit_vectorsearch)
  2. Qdrant 미연결   → LLM 경로 (submit) — graceful fallback
  3. LLM 오류       → Rule-based 경로 (RecommendService 내부 처리)

- POST /routines           : 추천 요청 접수 (Qdrant 연결 시 Vector, 미연결 시 LLM)
- GET  /routines/{task_id} : 추천 상태 조회 (폴링)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    get_task_executor,
    get_task_service,
    is_qdrant_available,
)
from app.core.exceptions import AppError
from app.schemas.v2.request import UserInputV2
from app.schemas.v2.response import TaskAcceptedResponse, TaskResult
from app.services.task.executor import TaskExecutor
from app.services.task.service import TaskService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/routines",
    response_model=TaskAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_recommendation(
    user_input: UserInputV2,
    task_service: TaskService = Depends(get_task_service),
    executor: TaskExecutor = Depends(get_task_executor),
    use_vector: bool = Depends(is_qdrant_available),
) -> TaskAcceptedResponse:
    """
    운동 루틴 추천 요청 접수 (V2: 비동기)

    Qdrant 연결 여부에 따라 추천 경로를 자동 선택한다.
      1. Qdrant 연결 성공 → VectorSearch 경로
      2. Qdrant 미연결   → LLM 경로 (graceful fallback)
      3. LLM 오류       → Rule-based 경로 (RecommendService 내부 처리)

    1. Task 생성 및 저장
    2. 백그라운드에서 추천 처리 시작 (경로는 use_vector에 따라 결정)
    3. taskId와 초기 상태 즉시 반환 (HTTP 202)

    Args:
    - user_input: 사용자 설문 + taskId + userId
    - task_service: Task 생명주기 관리 (DI) → deps.get_task_service
    - executor: 백그라운드 실행 워커 (DI) → deps.get_task_executor
    - use_vector: Qdrant 연결 여부 (DI) → deps.is_qdrant_available
    """
    logger.info(
        "V2 추천 요청 수신: taskId=%s, userId=%d, routineCount=%d, path=%s",
        user_input.taskId,
        user_input.userId,
        user_input.surveyData.routineCount,
        "vector" if use_vector else "llm",
    )

    try:
        task = task_service.create_task(user_input)
        if use_vector:
            executor.submit_vectorsearch(task.task_id)
        else:
            executor.submit(task.task_id)
    except AppError:
        raise
    except Exception:
        logger.exception("추천 요청 처리 중 예기치 않은 오류 [taskId=%s]", user_input.taskId)
        raise

    return TaskAcceptedResponse(taskId=task.task_id, userId=task.user_id)


@router.get("/routines/{task_id}", response_model=TaskResult)
async def get_recommendation_status(
    task_id: str,
    task_service: TaskService = Depends(get_task_service),
) -> TaskResult:
    """
    추천 태스크 상태 조회 (폴링)

    Args:
    - task_id: 조회할 Task ID
    - task_service: Task 생명주기 관리 (DI) → deps.get_task_service

    Returns:
    - IN_PROGRESS: 처리 중 (progress, currentStep 포함)
    - COMPLETED  : 완료 (routines, summary 포함)
    - FAILED     : 실패 (errorMessage 포함)
    - 404        : 존재하지 않는 task_id
    """
    result = task_service.get_task_status(task_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task not found: {task_id}",
        )
    return result
