# app/services/task_store.py
"""
Task 저장소 인터페이스 및 MVP 구현
- class TaskStore(Protocol) — 저장소 인터페이스
- class InMemoryTaskStore   — dict 기반 인메모리 구현체
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Protocol

from app.core.exceptions import TaskConflictError
from app.schemas.common import TaskStatus
from app.schemas.v2.task import TaskData

logger = logging.getLogger(__name__)

# 완료(COMPLETED/FAILED) 태스크 보존 시간 (초)
COMPLETED_TASK_TTL_SECONDS = 1800  # 30분
# 만료 태스크 정리 주기 (초)
CLEANUP_INTERVAL_SECONDS = 300  # 5분


class TaskStore(Protocol):
    """
    Task 저장소 인터페이스
    - 향후 Redis 등 외부 저장소로 교체 가능
    """

    def save(self, task: TaskData) -> None:
        """Task 저장 (중복 task_id 시 TaskConflictError 발생)"""
        ...

    def get(self, task_id: str) -> TaskData | None:
        """Task 조회 (없으면 None)"""
        ...

    def update(self, task_id: str, **fields: Any) -> None:
        """Task 필드 부분 업데이트"""
        ...


class InMemoryTaskStore:
    """
    MVP 구현체: dict 기반 인메모리 저장소
    - 서버 재시작 시 데이터 소실
    - 향후 Redis 구현체로 교체 가능
    - 완료(COMPLETED/FAILED) 태스크는 COMPLETED_TASK_TTL_SECONDS 후 자동 삭제
    """

    _TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED}

    def __init__(
        self,
        ttl_seconds: int = COMPLETED_TASK_TTL_SECONDS,
        cleanup_interval: int = CLEANUP_INTERVAL_SECONDS,
    ) -> None:
        self._store: dict[str, TaskData] = {}
        self._lock = threading.Lock()
        self._ttl_seconds = ttl_seconds
        self._start_cleanup_thread(cleanup_interval)

    def _start_cleanup_thread(self, interval: int) -> None:
        def _loop() -> None:
            while True:
                self._cleanup_event.wait(timeout=interval)
                if self._cleanup_event.is_set():
                    break
                self._purge_expired()

        self._cleanup_event = threading.Event()
        thread = threading.Thread(target=_loop, name="task-store-cleanup", daemon=True)
        thread.start()

    def _purge_expired(self) -> None:
        now = datetime.now(tz=timezone.utc)
        expired: list[str] = []

        with self._lock:
            for task_id, task in self._store.items():
                if task.status not in self._TERMINAL_STATUSES:
                    continue
                completed_at = task.completed_at
                if completed_at is None:
                    continue
                # completed_at이 timezone-naive인 경우 UTC로 간주
                if completed_at.tzinfo is None:
                    completed_at = completed_at.replace(tzinfo=timezone.utc)
                elapsed = (now - completed_at).total_seconds()
                if elapsed >= self._ttl_seconds:
                    expired.append(task_id)

            for task_id in expired:
                del self._store[task_id]

        if expired:
            logger.debug("만료된 태스크 %d건 삭제됨: %s", len(expired), expired)

    def save(self, task: TaskData) -> None:
        with self._lock:
            if task.task_id in self._store:
                raise TaskConflictError(f"Task already exists: {task.task_id}")
            self._store[task.task_id] = task
            logger.debug("Task 저장됨: %s", task.task_id)

    def get(self, task_id: str) -> TaskData | None:
        with self._lock:
            return self._store.get(task_id)

    def update(self, task_id: str, **fields: Any) -> None:
        with self._lock:
            task = self._store.get(task_id)

            if task is None:
                logger.warning("Task 업데이트 실패 (존재하지 않음): %s", task_id)
                return

            updated = task.model_copy(update=fields)
            self._store[task_id] = updated
