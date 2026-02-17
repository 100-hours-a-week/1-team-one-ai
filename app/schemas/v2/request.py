# app/schemas/v2/request.py
"""
V2 사용자 요청 데이터 스키마
- class UserInputV2(BaseModel)
"""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UserSurvey


class UserInputV2(BaseModel):
    """
    V2 추천 API의 request body
    - coreBE가 생성한 taskId를 포함하여 전달
    - userId 기준으로 기존 추천 이력 / 프로필 존재 여부 확인
        - cold start인 경우: 설문 기반 rule 추천
        - non-cold start인 경우: 벡터 기반 개인화 추천
    - callbackUrl은 Settings.CALLBACK_URL로 중앙 관리
    """

    model_config = ConfigDict(extra="forbid")

    taskId: str = Field(..., description="coreBE가 생성한 추천 태스크 ID")
    userId: int = Field(..., description="사용자 식별자 (cold start 여부 판단에 사용)")
    surveyData: UserSurvey = Field(..., description="사용자 설문 데이터")
