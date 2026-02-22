# app/schemas/v1/request.py
"""
사용자 요청 데이터 스키마
- class UserInputV1(BaseModel)
"""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UserSurvey


class UserInputV1(BaseModel):
    """
    v1 추천 API의 request body
    """

    model_config = ConfigDict(extra="forbid")  # 유효성 검사 시 추가 필드 금지

    surveyData: UserSurvey = Field(..., description="사용자 설문 데이터")
