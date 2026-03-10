# app/schemas/v2/task.py
"""
V2 Task 내부 상태 모델 (저장소용)
- class TaskData(BaseModel)
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.schemas.common import TaskStatus
from app.schemas.task import TaskResult, UserInput


class TaskData(BaseModel):
    """
    Task 상태 모델 (내부 저장소용)
    - API 응답이 아닌, 백그라운드 처리 상태를 추적하기 위한 모델
    """

    task_id: str
    user_id: int
    status: TaskStatus = TaskStatus.IN_PROGRESS
    progress: int = 0
    current_step: str = "추천 요청 접수됨"

    # 요청 데이터 (백그라운드에서 사용)
    request_data: UserInput

    # 결과 (완료 시)
    result: Optional[TaskResult] = None
    error_message: Optional[str] = None

    created_at: datetime
    completed_at: Optional[datetime] = None
