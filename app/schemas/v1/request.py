from typing import List, Optional

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


class UserActivityStats(BaseModel):
    """
    사용자 활동 통계 (v2 이상에서 사용)
    - v1에서는 request body에 포함되지 않음
    - 명시적으로 분리하여 버저닝 시 breaking change 방지
    """

    weeklyExerciseCount: Optional[int] = Field(None, ge=0, description="최근 1주일 운동 횟수")
    averageSittingHoursPerDay: Optional[float] = Field(
        None, ge=0, description="하루 평균 앉아있는 시간 (시간 단위)"
    )
    recentPainIncrease: Optional[bool] = Field(None, description="최근 통증 악화 여부")


class UserInputV1(BaseModel):
    """
    v1 추천 API의 request body
    - v2, v3에서는 이 모델을 확장한 V2/V3 모델 사용
    """

    model_config = ConfigDict(extra="forbid")

    surveyData: UserSurvey = Field(..., description="사용자 설문 데이터")
