# app/schemas/v1/request.py
"""
사용자 요청 데이터 스키마
- class SurveyAnswer(BaseModel)
- class UserSurvey(BaseModel)
- class UserInputV1(BaseModel)
"""

from typing import List

from pydantic import BaseModel, ConfigDict, Field


class SurveyAnswer(BaseModel):
    """
    설문 문항 1개에 대한 사용자 응답
    - 문항 텍스트는 v1 기준으로 그대로 전달
    - v2 이후 questionId 도입 가능
    """

    questionContent: str = Field(..., description="설문 문항 내용")
    selectedOptionSortOrder: int = Field(
        ..., ge=1, description="선택한 응답의 정렬 순서 (강도/빈도 등)"
    )


class UserSurvey(BaseModel):
    """
    사용자 설문 입력 (v1 기준 핵심 입력)
    - v2, v3에서 activityStats 가 병렬로 추가될 예정
    """

    routineCount: int = Field(..., ge=0, description="사용자가 원하는 루틴 개수")
    survey: List[SurveyAnswer] = Field(..., description="설문 응답 리스트")


class UserInputV1(BaseModel):
    """
    v1 추천 API의 request body
    - v2, v3에서는 이 모델을 확장한 V2/V3 모델 사용
    """

    model_config = ConfigDict(extra="forbid")  # 유효성 검사 시 추가 필드 금지

    surveyData: UserSurvey = Field(..., description="사용자 설문 데이터")
