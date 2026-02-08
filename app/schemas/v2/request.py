# app/schemas/v2/request.py
"""
V2 사용자 요청 데이터 스키마
- class UserSurvey(BaseModel) - v1과 동일
- class UserInputV2(BaseModel)
"""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.v1.request import UserSurvey


class UserInputV2(BaseModel):
    """
    V2 추천 API의 request body
    - coreBE가 생성한 taskId를 포함하여 전달
    - callbackUrl은 Settings.CALLBACK_URL로 중앙 관리
    """

    model_config = ConfigDict(extra="forbid")

    taskId: str = Field(..., description="coreBE가 생성한 추천 태스크 ID")
    surveyData: UserSurvey = Field(..., description="사용자 설문 데이터")
