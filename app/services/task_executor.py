# app/services/task_executor.py
"""
백그라운드 태스크 실행 인터페이스 및 구현체

- class TaskExecutor(Protocol)         — 실행 인터페이스 (어떤 워커를 쓸지 몰라도 됨)
- class BackgroundTaskExecutor         — FastAPI BackgroundTasks 기반 구현체 (현재 사용)

[교체 방법]
BackgroundTaskExecutor → CeleryTaskExecutor 로 교체 시:
1. CeleryTaskExecutor 클래스를 이 파일에 추가
2. recommend.py의 get_task_executor()에서 반환 타입만 변경

    class CeleryTaskExecutor:
        def submit(self, task_id: str) -> None:
            from app.workers.tasks import run_recommendation_task
            run_recommendation_task.delay(task_id)

    # recommend.py
    def get_task_executor() -> TaskExecutor:
        return CeleryTaskExecutor()   # BackgroundTasks 파라미터 불필요
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from fastapi import BackgroundTasks

    from app.services.task_service import TaskService

logger = logging.getLogger(__name__)


class TaskExecutor(Protocol):
    """
    백그라운드 태스크 실행 인터페이스

    역할: "추천 태스크를 백그라운드에서 실행한다"는 계약만 정의
    구현체가 FastAPI BackgroundTasks든 Celery든 엔드포인트는 이 인터페이스만 의존
    """

    def submit(self, task_id: str) -> None:
        """task_id에 해당하는 추천 작업을 백그라운드 큐에 제출"""
        ...


class BackgroundTaskExecutor:
    """
    FastAPI BackgroundTasks 기반 구현체

    동작 방식:
    - 서버 프로세스 내 스레드풀에서 task_service.run_recommendation 실행
    - 별도 워커 프로세스 없이 동작 (MVP 용도)

    한계:
    - 서버 재시작 시 실행 중인 태스크 소실
    - 재시도 / 모니터링 미지원
    → Celery 등 외부 워커로 교체하여 해결
    """

    def __init__(
        self,
        background_tasks: BackgroundTasks,
        task_service: TaskService,
    ) -> None:
        self._background_tasks = background_tasks
        self._task_service = task_service

    def submit(self, task_id: str) -> None:
        self._background_tasks.add_task(self._task_service.run_recommendation, task_id)
        logger.debug("백그라운드 태스크 제출: %s", task_id)
