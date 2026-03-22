# app/services/task/service.py
"""
Task 생명주기 오케스트레이터
- class TaskService — Task 생성, 백그라운드 추천 처리, 상태 조회
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.core.exceptions import AppError
from app.data.qdrant_exceptions import QdrantError
from app.schemas.common import TaskStatus
from app.schemas.task import (
    PROGRESS_STEP_PERCENTAGE,
    ProgressStep,
    TaskResult,
    UserInput,
)
from app.schemas.v2.task import TaskData
from app.services.callback_client import CallbackClient
from app.services.recommend.cf_recommend_service import CFRecommendService
from app.services.recommend.cold_start_checker import ColdStartChecker
from app.services.recommend.recommend_service import RecommendService
from app.services.recommend.vector_recommend_service import VectorRecommendService
from app.services.response.v2 import V2ResponseBuilder
from app.services.task.store import TaskStore
from app.utils.time import task_elapsed_sec

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

    - run_recommendation: LLM 기반 백그라운드 추천 처리 + 콜백 전송
    - run_vectorbased_recommendation: 벡터 검색 기반 백그라운드 추천 처리 + 콜백 전송
    - run_collab_recommendation: 협업 필터링 + 벡터 검색 기반 추천 처리 + 콜백 전송 (V3)
    """

    def __init__(
        self,
        store: TaskStore,
        recommend_service: RecommendService,
        response_builder: V2ResponseBuilder,
        callback_client: CallbackClient,
        cold_start_checker: ColdStartChecker,
        vector_recommend_service: VectorRecommendService | None = None,
        cf_recommend_service: CFRecommendService | None = None,
    ) -> None:
        self._store = store
        self._recommend_service = recommend_service
        self._response_builder = response_builder
        self._callback_client = callback_client
        self._cold_start_checker = cold_start_checker
        self._vector_recommend_service = vector_recommend_service
        self._cf_recommend_service = cf_recommend_service

    def create_task(self, user_input: UserInput) -> TaskData:
        """
        Task 생성 및 store에 저장 (상태: IN_PROGRESS)

        Args:
        - user_input: coreBE에서 전달받은 요청 데이터 (taskId 포함)

        Returns:
        - 생성된 TaskData
        """
        task = TaskData(
            task_id=user_input.taskId,
            user_id=user_input.userId,
            request_data=user_input,
            created_at=datetime.now(UTC),
        )
        self._store.save(task)
        logger.info("Task 생성 및 저장 완료 [task_id=%s, user_id=%d]", task.task_id, task.user_id)
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
            userId=task.user_id,
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
        2. 결과 검증 + 응답 빌드 (V2ResponseBuilder → TaskResult 직접 생성)
        3. Task 상태 업데이트
        4. coreBE 콜백 전송

        실패 시에도 콜백을 전송합니다.
        """
        task = self._store.get(task_id)

        if task is None:
            logger.error("Task를 찾을 수 없음: %s", task_id)
            return

        survey = task.request_data.surveyData
        user_id = task.user_id

        try:
            # Cold start 판단
            is_cold = self._cold_start_checker.is_cold_start(user_id)
            logger.info(
                "추천 시작 [task_id=%s, user_id=%d, cold_start=%s]",
                task_id,
                user_id,
                is_cold,
            )

            if is_cold:
                # Cold start: 설문 기반 추천 (현재 동작)
                self._update_progress(task_id, ProgressStep.LLM_INFERENCE)
                llm_output = self._recommend_service.recommend_routines(
                    survey=survey, user_id=user_id
                )
            else:
                # Non-cold start: 벡터 기반 개인화 추천 (미구현)
                # TODO: VectorRecommendService 구현 후 교체
                logger.info(
                    "Non-cold start 경로 미구현, cold start 경로로 fallback "
                    "[task_id=%s, user_id=%d]",
                    task_id,
                    user_id,
                )
                self._update_progress(task_id, ProgressStep.LLM_INFERENCE)
                llm_output = self._recommend_service.recommend_routines(
                    survey=survey, user_id=user_id
                )

            logger.debug(
                "LLM raw data(Cold start) [task_id=%s, user_id=%d]: %s",
                task_id,
                user_id,
                llm_output,
            )

            # Step 2: 결과 검증 + V2 응답 빌드 (TaskResult 직접 생성)
            self._update_progress(task_id, ProgressStep.RESULT_VALIDATION)
            result = self._response_builder.build(
                llm_output, task_id=task_id, survey=survey, user_id=user_id
            )

            # Step 3: 완료 처리
            self._store.update(
                task_id,
                status=TaskStatus.COMPLETED,
                progress=PROGRESS_STEP_PERCENTAGE[ProgressStep.COMPLETED],
                current_step=ProgressStep.COMPLETED.value,
                result=result,
                completed_at=result.completedAt,
            )
            if result.completedAt:
                elapsed = task_elapsed_sec(task.created_at, result.completedAt)
                logger.info(
                    "추천 완료 [task_id=%s, user_id=%d, elapsed=%.2fs, path=llm]",
                    task_id,
                    user_id,
                    elapsed,
                )
            else:
                logger.info("추천 완료 [task_id=%s, user_id=%d]", task_id, user_id)

            # Step 4: 콜백 전송 (성공)
            self._send_callback(result)

        except AppError as e:
            self._handle_failure(task_id, str(e), user_id=user_id)

        except Exception as e:
            logger.exception("예상치 못한 오류 [task_id=%s, user_id=%d]", task_id, user_id)
            self._handle_failure(task_id, f"unexpected error: {e}", user_id=user_id)

    def run_vectorbased_recommendation(self, task_id: str) -> None:
        """
        백그라운드에서 실행되는 벡터 검색 기반 추천 처리 로직

        1. 설문 → 쿼리 임베딩 → Qdrant 유사도 검색
            VectorRecommendService.recommend_routines() 내부에서 다음 흐름으로 처리:
            1. _build_query(survey) → query string
            2. embedding_model.encode(query) → vector
            3. exercise_repo.search(vector, limit=20) → hits
            4. _build_routine_list(hits, survey.routineCount) → RoutineList (fallback reason)

        2. 결과 검증 + 보정 (V2ResponseBuilder → TaskResult)
        3. LLM reason 생성 (검증 & 보정 완료된 최종 steps 기반)
        4. Task 상태 업데이트
        5. coreBE 콜백 전송

        실패 시에도 콜백을 전송합니다.
        """
        from app.core.exceptions import ConfigurationError

        task = self._store.get(task_id)

        if task is None:
            logger.error("Task를 찾을 수 없음: %s", task_id)
            return

        survey = task.request_data.surveyData
        user_id = task.user_id

        try:
            if self._vector_recommend_service is None:
                raise ConfigurationError("VectorRecommendService가 주입되지 않았습니다.")

            logger.info(
                "벡터 검색 추천 시작 [task_id=%s, user_id=%d]",
                task_id,
                user_id,
            )

            # Step 1: 설문 분석 + 쿼리 생성
            self._update_progress(task_id, ProgressStep.HEALTH_SCORE)

            # Step 2: 벡터 검색 (임베딩 + Qdrant)
            self._update_progress(task_id, ProgressStep.EXERCISE_SEARCH)
            vector_output = self._vector_recommend_service.recommend_routines(
                survey=survey, user_id=user_id
            )

            logger.debug(
                "벡터 검색 결과 [task_id=%s, user_id=%d]: routines=%d",
                task_id,
                user_id,
                len(vector_output.routines),
            )

            # Step 3: 결과 검증 + 보정 (유효성 검증, bilateral rule, 시간 보정)
            self._update_progress(task_id, ProgressStep.RESULT_VALIDATION)
            result = self._response_builder.build(
                vector_output, task_id=task_id, survey=survey, user_id=user_id
            )

            # Step 4: LLM reason 생성 (검증 & 보정 완료된 최종 steps 기반)
            if result.routines:
                self._update_progress(task_id, ProgressStep.REASON_GENERATION)
                reasoned_routines = self._vector_recommend_service.generate_reasons(
                    result.routines, survey
                )
                # reason 생성 완료 후 completedAt 재설정 (LLM 호출 시간 반영)
                result = result.model_copy(
                    update={"routines": reasoned_routines, "completedAt": datetime.now(UTC)}
                )

            # Step 5: 완료 처리
            self._store.update(
                task_id,
                status=TaskStatus.COMPLETED,
                progress=PROGRESS_STEP_PERCENTAGE[ProgressStep.COMPLETED],
                current_step=ProgressStep.COMPLETED.value,
                result=result,
                completed_at=result.completedAt,
            )
            if result.completedAt:
                elapsed = task_elapsed_sec(task.created_at, result.completedAt)
                logger.info(
                    "벡터 검색 추천 완료 [task_id=%s, user_id=%d, elapsed=%.2fs, path=vector]",
                    task_id,
                    user_id,
                    elapsed,
                )
            else:
                logger.info("벡터 검색 추천 완료 [task_id=%s, user_id=%d]", task_id, user_id)

            # Step 6: 콜백 전송 (성공)
            self._send_callback(result)

        except QdrantError as e:
            logger.warning(
                "Qdrant 오류 감지 — LLM 경로로 fallback [task_id=%s, user_id=%d]: %s",
                task_id,
                user_id,
                e,
            )
            self.run_recommendation(task_id)

        except AppError as e:
            self._handle_failure(task_id, str(e), user_id=user_id)

        except Exception as e:
            logger.exception(
                "벡터 검색 추천 예상치 못한 오류 [task_id=%s, user_id=%d]", task_id, user_id
            )
            self._handle_failure(task_id, f"unexpected error: {e}", user_id=user_id)

    def run_collab_recommendation(self, task_id: str) -> None:
        """
        백그라운드에서 실행되는 협업 필터링 + 벡터 검색 혼합 추천 처리 로직 (V3)

        1. 설문 → 쿼리 임베딩 + 사용자 만족도 기반 유사 사용자 검색
            CFRecommendService.recommend_routines() 내부 흐름:
            1. _build_query(survey) → query string
            2. embedding_model.encode(query) → survey vector (+ 활동 벡터 블렌딩)
            3. exercise_repo.search(vector) → 벡터 유사도 점수
            4. satisfaction_repo.get_user_satisfaction(user_id) → 사용자 만족도
            5. satisfaction_repo.search_similar_users(ratings) → 유사 사용자
            6. _blend_and_rank(vector_scores, cf_scores) → 최종 운동 순위
            7. _build_routine_list(ranked_hits) → RoutineList

        2. 결과 검증 + 보정 (V2ResponseBuilder → TaskResult)
        3. LLM reason 생성 (검증 & 보정 완료된 최종 steps 기반)
        4. Task 상태 업데이트
        5. coreBE 콜백 전송

        만족도 데이터 없음 / 유사 사용자 없음 → 벡터 검색만으로 graceful fallback.
        Qdrant 오류 → LLM 경로로 fallback.
        실패 시에도 콜백을 전송합니다.
        """
        from app.core.exceptions import ConfigurationError

        task = self._store.get(task_id)

        if task is None:
            logger.error("Task를 찾을 수 없음: %s", task_id)
            return

        survey = task.request_data.surveyData
        user_id = task.user_id

        try:
            if self._cf_recommend_service is None:
                raise ConfigurationError("CFRecommendService가 주입되지 않았습니다.")

            logger.info(
                "CF 혼합 추천 시작 [task_id=%s, user_id=%d]",
                task_id,
                user_id,
            )

            # Step 1: 설문 분석 + 쿼리 생성
            self._update_progress(task_id, ProgressStep.HEALTH_SCORE)

            # Step 2: 벡터 검색 + CF 점수 블렌딩
            self._update_progress(task_id, ProgressStep.EXERCISE_SEARCH)
            cf_output = self._cf_recommend_service.recommend_routines(
                survey=survey, user_id=user_id
            )

            logger.debug(
                "CF 혼합 추천 결과 [task_id=%s, user_id=%d]: routines=%d",
                task_id,
                user_id,
                len(cf_output.routines),
            )

            # Step 3: 결과 검증 + 보정 (유효성 검증, bilateral rule, 시간 보정)
            self._update_progress(task_id, ProgressStep.RESULT_VALIDATION)
            result = self._response_builder.build(
                cf_output, task_id=task_id, survey=survey, user_id=user_id
            )

            # Step 4: LLM reason 생성 (검증 & 보정 완료된 최종 steps 기반)
            if result.routines:
                self._update_progress(task_id, ProgressStep.REASON_GENERATION)
                reasoned_routines = self._cf_recommend_service.generate_reasons(
                    result.routines, survey
                )
                # reason 생성 완료 후 completedAt 재설정 (LLM 호출 시간 반영)
                result = result.model_copy(
                    update={"routines": reasoned_routines, "completedAt": datetime.now(UTC)}
                )

            # Step 5: 완료 처리
            self._store.update(
                task_id,
                status=TaskStatus.COMPLETED,
                progress=PROGRESS_STEP_PERCENTAGE[ProgressStep.COMPLETED],
                current_step=ProgressStep.COMPLETED.value,
                result=result,
                completed_at=result.completedAt,
            )
            if result.completedAt:
                elapsed = task_elapsed_sec(task.created_at, result.completedAt)
                logger.info(
                    "V3 추천 완료 [task_id=%s, user_id=%d, elapsed=%.2fs, path=cf]",
                    task_id,
                    user_id,
                    elapsed,
                )
            else:
                logger.info("V3 추천 완료 [task_id=%s, user_id=%d]", task_id, user_id)

            # Step 6: 콜백 전송 (성공)
            self._send_callback(result)

        except QdrantError as e:
            logger.warning(
                "Qdrant 오류 감지 — LLM 경로로 fallback [task_id=%s, user_id=%d]: %s",
                task_id,
                user_id,
                e,
            )
            self.run_recommendation(task_id)

        except AppError as e:
            self._handle_failure(task_id, str(e), user_id=user_id)

        except Exception as e:
            logger.exception(
                "CF 혼합 추천 예상치 못한 오류 [task_id=%s, user_id=%d]", task_id, user_id
            )
            self._handle_failure(task_id, f"unexpected error: {e}", user_id=user_id)

    def _update_progress(self, task_id: str, step: ProgressStep) -> None:
        """진행 상태 업데이트"""
        self._store.update(
            task_id,
            progress=PROGRESS_STEP_PERCENTAGE[step],
            current_step=step.value,
        )
        logger.debug(
            "진행 상태 업데이트 [task_id=%s]: %s (%d%%)",
            task_id,
            step.value,
            PROGRESS_STEP_PERCENTAGE[step],
        )

    def _handle_failure(self, task_id: str, error_message: str, *, user_id: int) -> None:
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
        logger.error("추천 실패 [task_id=%s, user_id=%d]: %s", task_id, user_id, error_message)

        failure_result = self._response_builder.build_failed(
            task_id=task_id, error_message=error_message, user_id=user_id
        )
        self._callback_client.send(failure_result)

    def _send_callback(self, result: TaskResult) -> None:
        """콜백 전송 (URL은 CallbackClient가 Settings에서 관리)"""
        self._callback_client.send(result)
