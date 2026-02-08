# app/services/task_service.py
"""
Task 생명주기 오케스트레이터
- class TaskService — Task 생성, 백그라운드 추천 처리, 상태 조회
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.core.exceptions import AppError
from app.schemas.v2.request import UserInputV2
from app.schemas.v2.response import (
    PROGRESS_STEP_PERCENTAGE,
    ProgressStep,
    RecommendationSummary,
    TaskResult,
    TaskStatus,
)
from app.schemas.v2.task import TaskData
from app.services.callback_client import CallbackClient
from app.services.recommend_service import RecommendService
from app.services.response_builder import ResponseBuilder
from app.services.task_store import TaskStore

logger = logging.getLogger(__name__)


class TaskService:
    """
    Task 생명주기 관리

    - create_task: Task 생성 + 저장
        - Args: user_input: coreBE에서 전달받은 요청 데이터 (taskId 포함)
        - Returns: 생성된 TaskData

    - get_task_status: Task 상태 조회 (폴링용)
        - Args: task_id: 조회할 Task ID
        - Returns: TaskResult 또는 None (존재하지 않을 경우)

    - run_recommendation: 백그라운드 추천 처리 + 콜백 전송

    """

    def __init__(
        self,
        store: TaskStore,
        recommend_service: RecommendService,
        response_builder: ResponseBuilder,
        callback_client: CallbackClient,
    ) -> None:
        self._store = store
        self._recommend_service = recommend_service
        self._response_builder = response_builder
        self._callback_client = callback_client

    def create_task(self, user_input: UserInputV2) -> TaskData:
        """
        Task 생성 및 store에 저장 (상태: IN_PROGRESS)

        Args:
        - user_input: coreBE에서 전달받은 요청 데이터 (taskId 포함)

        Returns:
        - 생성된 TaskData
        """
        task = TaskData(
            task_id=user_input.taskId,
            request_data=user_input,
            created_at=datetime.now(UTC),
        )
        self._store.save(task)
        logger.info("Task 생성: %s", task.task_id)
        return task

    def get_task_status(self, task_id: str) -> TaskResult | None:
        """
        Task 상태 조회 (폴링 엔드포인트용)

        Args:
        - task_id: 조회할 Task ID

        Returns:
        - TaskResult 또는 None (존재하지 않을 경우)
        """
        task = self._store.get(task_id)

        if task is None:
            return None

        return TaskResult(
            taskId=task.task_id,
            status=task.status,
            progress=task.progress,
            currentStep=task.current_step,
            summary=task.result.summary if task.result else None,
            errorMessage=task.error_message,
            completedAt=task.completed_at,
            routines=task.result.routines if task.result else None,
        )

    def run_recommendation(self, task_id: str) -> None:
        """
        백그라운드에서 실행되는 추천 처리 로직

        1. LLM 추천 호출
        2. 결과 검증 + 응답 빌드
        3. Task 상태 업데이트
        4. coreBE 콜백 전송

        실패 시에도 콜백을 전송합니다.

        Args:
        - task_id: 조회할 Task ID

        Returns:
        - None
        """
        task = self._store.get(task_id)

        if task is None:
            logger.error("Task를 찾을 수 없음: %s", task_id)
            return

        survey = task.request_data.surveyData

        try:
            # Step 1: LLM 추천
            self._update_progress(task_id, ProgressStep.LLM_INFERENCE)
            llm_output = self._recommend_service.recommend_routines(survey=survey)

            # Step 2: 결과 검증 + 응답 빌드
            self._update_progress(task_id, ProgressStep.RESULT_VALIDATION)
            v1_response = self._response_builder.build(llm_output, task_id=task_id, survey=survey)

            # Step 3: 완료 처리
            now = datetime.now(UTC)
            result = TaskResult(
                taskId=task_id,
                status=TaskStatus.COMPLETED,
                progress=PROGRESS_STEP_PERCENTAGE[ProgressStep.COMPLETED],
                currentStep=ProgressStep.COMPLETED.value,
                errorMessage=None,
                summary=RecommendationSummary(
                    totalRoutines=v1_response.summary.totalRoutines,
                    totalExercises=v1_response.summary.totalExercises,
                )
                if v1_response.summary
                else None,
                completedAt=now,
                routines=[routine.model_copy() for routine in v1_response.routines]
                if v1_response.routines
                else None,
            )

            self._store.update(
                task_id,
                status=TaskStatus.COMPLETED,
                progress=PROGRESS_STEP_PERCENTAGE[ProgressStep.COMPLETED],
                current_step=ProgressStep.COMPLETED.value,
                result=result,
                completed_at=now,
            )
            logger.info("추천 완료 [task_id=%s]", task_id)

            # Step 4: 콜백 전송 (성공)
            self._send_callback(result)

        except AppError as e:
            self._handle_failure(task_id, str(e))

        except Exception as e:
            logger.exception("예상치 못한 오류 [task_id=%s]", task_id)
            self._handle_failure(task_id, f"unexpected error: {e}")

    def _update_progress(self, task_id: str, step: ProgressStep) -> None:
        """진행 상태 업데이트"""
        self._store.update(
            task_id,
            progress=PROGRESS_STEP_PERCENTAGE[step],
            current_step=step.value,
        )
        logger.debug(
            "진행 업데이트 [task_id=%s]: %s (%d%%)",
            task_id,
            step.value,
            PROGRESS_STEP_PERCENTAGE[step],
        )

    def _handle_failure(self, task_id: str, error_message: str) -> None:
        """실패 처리 + 콜백 전송"""
        now = datetime.now(UTC)
        self._store.update(
            task_id,
            status=TaskStatus.FAILED,
            progress=PROGRESS_STEP_PERCENTAGE[ProgressStep.FAILED],
            current_step=ProgressStep.FAILED.value,
            error_message=error_message,
            completed_at=now,
        )
        logger.error("추천 실패 [task_id=%s]: %s", task_id, error_message)

        failure_result = TaskResult(
            taskId=task_id,
            status=TaskStatus.FAILED,
            progress=PROGRESS_STEP_PERCENTAGE[ProgressStep.FAILED],
            currentStep=ProgressStep.FAILED.value,
            errorMessage=error_message,
            completedAt=now,
            summary=None,
            routines=None,
        )
        self._callback_client.send(failure_result)

    def _send_callback(self, result: TaskResult) -> None:
        """콜백 전송 (URL은 CallbackClient가 Settings에서 관리)"""
        self._callback_client.send(result)
