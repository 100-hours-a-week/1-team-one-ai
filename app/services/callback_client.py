# app/services/callback_client.py
"""
coreBE 콜백 HTTP 클라이언트
- class CallbackClient — 추천 결과를 coreBE에 POST 전송
- callback URL은 Settings.CALLBACK_URL에서 중앙 관리
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import CallbackPolicy, settings
from app.schemas.task import TaskResult

logger = logging.getLogger(__name__)


class CallbackClient:
    """
    coreBE에 추천 결과를 전송하는 HTTP 클라이언트
    - 실패 시 로그만 남기고 예외를 전파하지 않음
    - 최대 1회 재시도
    - callback URL은 Settings.CALLBACK_URL 사용
    """

    def send(self, payload: TaskResult) -> bool:
        """
        Settings.CALLBACK_URL로 POST 요청 전송

        Args:
        - payload: 전송할 페이로드

        Returns:
        - True: 전송 성공, False: 전송 실패 또는 URL 미설정
        """
        callback_url = settings.CALLBACK_URL
        if not callback_url:
            logger.warning(
                "CALLBACK_URL 미설정 - 콜백 전송 건너뜀 [task_id=%s, user_id=%d]",
                payload.taskId,
                payload.userId,
            )
            return False

        body = payload.model_dump(mode="json", exclude_none=True)

        for attempt in range(CallbackPolicy.MAX_RETRIES + 1):
            try:
                response = httpx.post(
                    callback_url,
                    json=body,
                    timeout=CallbackPolicy.TIMEOUT_SEC,
                )
                response.raise_for_status()

                logger.info(
                    "콜백 전송 성공 [task_id=%s, user_id=%d, url=%s, status=%d]",
                    payload.taskId,
                    payload.userId,
                    callback_url,
                    response.status_code,
                )
                return True

            except httpx.TimeoutException:
                logger.warning(
                    "콜백 전송 타임아웃 (시도 %d/%d) [task_id=%s, url=%s]",
                    attempt + 1,
                    CallbackPolicy.MAX_RETRIES + 1,
                    payload.taskId,
                    callback_url,
                )
            except httpx.HTTPStatusError as e:
                logger.warning(
                    "콜백 전송 HTTP 에러 (시도 %d/%d) [task_id=%s, url=%s, status=%d]",
                    attempt + 1,
                    CallbackPolicy.MAX_RETRIES + 1,
                    payload.taskId,
                    callback_url,
                    e.response.status_code,
                )
            except httpx.HTTPError as e:
                logger.warning(
                    "콜백 전송 실패 (시도 %d/%d) [task_id=%s, url=%s]: %s",
                    attempt + 1,
                    CallbackPolicy.MAX_RETRIES + 1,
                    payload.taskId,
                    callback_url,
                    e,
                )

        logger.error(
            "콜백 전송 최종 실패 [task_id=%s, user_id=%d, url=%s]",
            payload.taskId,
            payload.userId,
            callback_url,
        )
        return False
