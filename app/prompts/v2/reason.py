# app/prompts/v2/reason.py
"""루틴 추천 이유 생성용 프롬프트 (벡터 검색 추천)"""

from __future__ import annotations

from app.domain.exercise import BaseExercise, BodyPart
from app.schemas.common import SurveyAnswer, UserSurvey

REASON_SYSTEM_PROMPT = """\
운동 루틴 추천 이유를 작성하는 헬스케어 도우미입니다.

## 출력 규칙
1. 한국어로 정확히 1문장(35자 이상, 65자 이내)을 작성합니다.
2. 운동 이름·구체적 동작명은 절대 언급하지 않습니다.
3. 루틴 효과 정보에 나열된 신체 부위와 기대 효과를 중심으로 작성합니다. 루틴에 포함되지 않은 신체 부위는 절대 언급하지 않습니다.
4. 점수·수치·시스템 표현(예: "4/5", "점수", "단계")은 절대 사용하지 않습니다.
5. 이유 텍스트만 출력합니다. JSON, 마크다운, 따옴표 없이.

## 좋은 예시
- "목과 어깨 긴장이 쌓이기 쉬운 하루를 위해 뭉친 근육을 부드럽게 풀어드려요."
- "오래 앉아 굳은 허리와 목을 편안하게 회복시켜 가볍게 마무리할 수 있어요."
- "눈의 피로가 쌓이셨다면, 눈 주변 근육을 편안하게 풀어주는 루틴이에요."

## 나쁜 예시 (절대 금지)
- "목 전굴 스트레칭과..." (운동 이름 언급)
- "어깨를 크게 돌리고..." (구체적 동작 언급)
- "점수가 높아..." / "4/5이므로..." (수치 노출)
- 루틴에 없는 신체 부위 언급 (예: 목·어깨 루틴에서 "눈 피로" 언급)
"""

_SEVERITY_LABEL: dict[int, str] = {
    1: "거의 없음",
    2: "약간 있음",
    3: "보통",
    4: "상당히 있음",
    5: "매우 심함",
}

_USER_PROMPT_TEMPLATE = """\
## 사용자 설문 응답
{survey_text}

## 루틴 효과 정보 (운동 이름·동작명 언급 금지, 부위와 효과만 활용)
{exercises_text}

이 루틴을 추천한 이유를 1문장(35-65자)으로 작성하세요.
불편한 부위와 기대 효과를 연결하되, 운동 이름이나 구체적 동작은 언급하지 마세요.
"""


# 신체 부위 → 설문 문항 키워드 매핑
_BODY_PART_KEYWORDS: dict[BodyPart, list[str]] = {
    BodyPart.NECK: ["목"],
    BodyPart.SHOULDER: ["어깨"],
    BodyPart.WRIST: ["손목"],
    BodyPart.LOWER_BACK: ["허리"],
    BodyPart.EYES: ["눈"],
}

# 루틴 부위와 무관하게 맥락 제공을 위해 항상 포함할 키워드
_ALWAYS_INCLUDE_KEYWORDS = ["앉아", "신체 피로"]


def _filter_survey_by_exercises(
    survey: UserSurvey, exercises: list[BaseExercise]
) -> list[SurveyAnswer]:
    """루틴 운동의 bodyPart에 해당하는 설문 항목만 반환.

    관련 설문 항목이 없으면 전체 설문 반환 (fallback).
    """
    body_parts = {ex.bodyPart for ex in exercises}
    relevant_keywords: set[str] = set(_ALWAYS_INCLUDE_KEYWORDS)
    for bp in body_parts:
        relevant_keywords.update(_BODY_PART_KEYWORDS.get(bp, []))

    filtered = [
        a for a in survey.survey if any(kw in a.questionContent for kw in relevant_keywords)
    ]
    return filtered or survey.survey


def _format_survey_answers(answers: list[SurveyAnswer]) -> str:
    lines = []
    for a in answers:
        severity = _SEVERITY_LABEL.get(a.selectedOptionSortOrder, str(a.selectedOptionSortOrder))
        lines.append(f"- {a.questionContent} → {severity}")
    return "\n".join(lines)


def _format_exercises(exercises: list[BaseExercise]) -> str:
    lines = []
    for ex in exercises:
        lines.append(f"- 부위: {ex.bodyPart.value} | 효과: {ex.effect} | 태그: {ex.tags}")
    return "\n".join(lines)


def build_reason_prompt(survey: UserSurvey, exercises: list[BaseExercise]) -> str:
    relevant_answers = _filter_survey_by_exercises(survey, exercises)
    return _USER_PROMPT_TEMPLATE.format(
        survey_text=_format_survey_answers(relevant_answers),
        exercises_text=_format_exercises(exercises),
    )
