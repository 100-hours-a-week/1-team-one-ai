# app/prompts/v2/reason.py
"""루틴 추천 이유 생성용 프롬프트 (벡터 검색 추천)"""

from __future__ import annotations

from app.schemas.common import UserSurvey

REASON_SYSTEM_PROMPT = """\
운동 루틴 추천 이유를 작성하는 도우미입니다.

## 규칙
1. 한국어로 1~2문장, 친근하고 자연스러운 어투로 작성합니다.
2. 사용자 설문 내용과 루틴 구성 운동을 연결하여 설명합니다.
3. 점수·수치·시스템적 표현(예: "4/5", "점수가 높아")은 사용하지 않습니다.
4. 이유 텍스트만 출력합니다. JSON, 마크다운, 따옴표 없이.
"""

_USER_PROMPT_TEMPLATE = """\
사용자 설문 응답:
{survey_text}

이 루틴에 포함된 운동:
{exercises_text}

이 루틴을 추천한 이유를 친근하게 1~2문장으로 설명해주세요.
"""


def build_reason_prompt(survey: UserSurvey, exercise_names: list[str]) -> str:
    survey_text = "\n".join(
        f"- {a.questionContent}: {a.selectedOptionSortOrder}" for a in survey.survey
    )
    exercises_text = ", ".join(exercise_names)
    return _USER_PROMPT_TEMPLATE.format(
        survey_text=survey_text,
        exercises_text=exercises_text,
    )
