# app/prompts/v1/recommend.py

from pathlib import Path
from typing import List

from app.schemas.v1.request import SurveyAnswer, UserSurvey

"""
운동 루틴 추천용 프롬프트 (OpenAI)
- SYSTEM_PROMPT
- OUTPUT_SCHEMA
- USER_PROMPT_TEMPLATE
- def build_user_prompt(
    routine_count: int,
    survey_text: str,
    exercises_text: str
) -> str
"""

DATA_DIR = Path(__file__).parent
EXERCISES_PATH = DATA_DIR / "routines_shots.json"
FEW_SHOT = EXERCISES_PATH.read_text(encoding="utf-8")

SYSTEM_PROMPT = """\
You are an exercise routine recommendation assistant.

## Strict Rules
1. Output ONLY valid JSON. No markdown, no comments, no extra text.
2. Use ONLY id values from "Available Exercises". NEVER invent new IDs.
3. Copy the "type" field exactly from the exercise data. Do NOT change REPS to DURATION or vice versa.
4. If type is DURATION: set durationTime (seconds), set targetReps to null.
5. If type is REPS: set targetReps (count), set durationTime to null.
6. Each routine must have 3-5 steps.

## Validation Checklist (self-check before output)
- [ ] Every id exists in Available Exercises?
- [ ] Every type matches the original exercise type?
- [ ] DURATION exercises have durationTime, REPS exercises have targetReps?
"""

OUTPUT_SCHEMA = """\
{
  "routines": [
    {
      "routineOrder": <int, 루틴 순서, 1부터 시작>,
      "reason": "<string, 한국어, 이 루틴을 추천한 이유, 사용자 설문과 연관지어 설명>",
      "steps": [
        {
          "exerciseId": "<string, Available Exercises에 존재하는 ID만 사용 가능>",
          "type": "<string, 해당 운동의 원본 type을 그대로 복사. REPS 또는 DURATION>",
          "stepOrder": <int, 루틴 내 운동 순서, 1부터 시작>,
          "limitTime": <int, 이 스텝에 허용된 최대 시간(초), 예: 30~60>,
          "durationTime": <int|null, type이 DURATION일 때 실제 수행 시간(초). REPS면 null>,
          "targetReps": <int|null, type이 REPS일 때 목표 반복 횟수. DURATION이면 null>
        }
      ]
    }
  ]
}
"""

USER_PROMPT_TEMPLATE = """\
## User Survey
- Requested routines: {routine_count}
- Survey responses:
{survey_text}

## Available Exercises
{exercises_text}

## Output Schema
{output_schema}

Generate {routine_count} exercise routines based on the user survey.

## Example
{example}
"""


def survey_to_text(survey: List[SurveyAnswer]) -> str:
    """설문 응답을 텍스트로 변환"""
    return "\n".join(f"- {item.questionContent}: {item.selectedOptionSortOrder}" for item in survey)


def build_user_prompt(
    user: UserSurvey,
    exercises_text: str,
) -> str:
    """유저 프롬프트 만들기"""
    return USER_PROMPT_TEMPLATE.format(
        routine_count=user.routineCount,
        survey_text=survey_to_text(user.survey),
        exercises_text=exercises_text,
        output_schema=OUTPUT_SCHEMA,
        example=FEW_SHOT,
    )
