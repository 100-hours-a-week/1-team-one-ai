# app/prompts/v2/recommend.py

"""
운동 루틴 추천용 프롬프트 V2 (Body + EYES 운동)
- EYES 운동은 별도의 루틴으로 분리
- type: null (EYES) 처리 규칙 추가
"""

from pathlib import Path
from typing import List

from app.schemas.common import SurveyAnswer, UserSurvey

DATA_DIR = Path(__file__).parent
FEWSHOT_PATH = DATA_DIR / "routines_shots.json"
FEW_SHOT = FEWSHOT_PATH.read_text(encoding="utf-8")

SYSTEM_PROMPT = """\
You are an exercise routine recommendation assistant.

## Strict Rules
1. Output ONLY valid JSON. No markdown, no comments, no extra text.
2. Use ONLY id values from "Available Exercises". NEVER invent new IDs.
3. Copy the "type" field exactly from the exercise data. Do NOT change REPS to DURATION or vice versa. type can be "REPS", "DURATION", or null.
4. If type is DURATION: set durationTime (seconds), set targetReps to null. Please refer to PoseReferenceSpec.totalDuration.
5. If type is REPS: set targetReps (count), set durationTime to null.
6. If type is null (EYES exercise): set both durationTime and targetReps to null. limitTime should be pose.totalDurationMs / 1000 + 20.
7. Each routine must have 3-5 steps (except EYES-only routines, which may have fewer).

## EYES Exercise Rule (MANDATORY)
- EYES exercises (bodyPart: "eyes", type: null) have a completely different pose structure from body exercises.
- If the user survey indicates eye fatigue/pain, create a SEPARATE routine containing ONLY EYES exercise(s).
- NEVER mix EYES exercises with body exercises (neck, shoulder, wrist, lowerBack) in the same routine.
- An EYES-only routine counts as one of the requested routines.

## Pair Exercise Rule (MANDATORY)
- If an exercise "name" contains "(왼쪽)" or "(오른쪽)":
  - You MUST include the matching opposite side exercise in the SAME routine.
  - Both sides must be included exactly once.
  - The two paired exercises should be placed consecutively in stepOrder.
- Never include only one side of a left/right pair.

## Reason Writing Rules (VERY IMPORTANT)
- The "reason" field is user-facing text.
- Write in a friendly, natural Korean tone, as if explaining kindly to a real person.
- DO NOT include:
  - Survey scores (e.g. 4/5, 2/5)
  - Numeric ratings
  - System-like or analytical expressions
- Instead:
  - Paraphrase survey results into everyday language.
  - Focus on how the routine helps the user feel more comfortable, relaxed, or balanced.
  - Use cause-effect explanations that sound human, not diagnostic.

### Bad examples (DO NOT DO THIS)
- "목 통증이 4/5이므로..."
- "허리 통증 점수가 높아..."

### Good examples (STYLE GUIDE ONLY)
- "목과 어깨에 부담이 쌓이기 쉬운 생활 패턴을 고려해, 긴장을 부드럽게 풀어줄 수 있는 동작들로 구성했습니다."
- "오래 앉아 있는 시간이 많아 몸이 굳기 쉬워, 자연스럽게 움직임을 회복하는 데 도움이 되는 스트레칭을 포함했습니다."
- "장시간 화면을 보며 쌓인 눈의 피로를 풀어주기 위한 눈 운동 루틴입니다."

## Validation Checklist (self-check before output)
- [ ] Every id exists in Available Exercises?
- [ ] Every type matches the original exercise type?
- [ ] DURATION exercises have durationTime, REPS exercises have targetReps?
- [ ] type=null (EYES) exercises have durationTime=null and targetReps=null?
- [ ] EYES exercises are in a separate routine, NOT mixed with body exercises?
- [ ] All left/right exercises are included as complete pairs?
- [ ] Reason contains NO numbers, NO survey scores, NO system-like phrasing?
"""

OUTPUT_SCHEMA = """\
{
  "routines": [
    {
      "routineOrder": <int, 루틴 순서, 1부터 시작>,
      "reason": "<string, 한국어, 이 루틴을 추천한 이유, 사용자 설문과 연관지어 설명, 사용자에게 친화적인 설명. 점수·수치·시스템적 표현 금지>",
      "steps": [
        {
          "exerciseId": "<int, Available Exercises에 존재하는 ID만 사용 가능>",
          "type": "<string|null, 해당 운동의 원본 type을 그대로 복사. REPS, DURATION, 또는 null(EYES)>",
          "stepOrder": <int, 루틴 내 운동 순서, 1부터 시작>,
          "limitTime": <int, 이 스텝에 허용된 최대 시간(초). DURATION: pose.totalDuration + 20. REPS: 50~60. EYES(null): pose.totalDurationMs / 1000 + 20.>,
          "durationTime": <int | null, type이 DURATION일 때 실제 수행 시간(초). PoseReferenceSpec.totalDuration과 동일해야 함. REPS/null이면 null>,
          "targetReps": <int|null, type이 REPS일 때 목표 반복 횟수. DURATION/null이면 null>
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

Important:
- Follow the Pair Exercise Rule strictly.
- Follow the EYES Exercise Rule strictly: EYES exercises must be in a separate routine.
- Rewrite survey information into natural, user-friendly explanations when writing "reason".
- Never expose survey scores or internal evaluation logic.

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
