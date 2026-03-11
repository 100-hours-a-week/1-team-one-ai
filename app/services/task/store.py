# app/services/task_store.py
"""
Task 저장소 인터페이스 및 MVP 구현
- class TaskStore(Protocol) — 저장소 인터페이스
- class InMemoryTaskStore   — dict 기반 인메모리 구현체
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Protocol

from app.core.exceptions import TaskConflictError
from app.schemas.v2.task import TaskData

logger = logging.getLogger(__name__)


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
    """

    def __init__(self) -> None:
        self._store: dict[str, TaskData] = {}
        self._lock = threading.Lock()

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
