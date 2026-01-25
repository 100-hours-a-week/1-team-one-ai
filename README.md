# Recommendation API

추천 서비스 백엔드 API

## 요구사항

- Python 3.11.x
- [uv](https://docs.astral.sh/uv/) (패키지 매니저)
- Docker (배포 시)

## 로컬 실행

```bash
# 의존성 설치
uv sync

# 환경변수 설정
cp .env.example .env

# 서버 실행
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 # --reload
```

## 환경변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `HOST` | 서버 호스트 | `0.0.0.0` |
| `PORT` | 서버 포트 | `8000` |
| `OPENAI_API_KEY` | OPENAI API 키 | - |
| `GEMINI_API_KEY` | GEMINI API 키 | - |
| `OLLAMA_API_KEY` | OLLAMA API 키 | - |

## API 엔드포인트

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | 헬스체크 |
| `GET` | `/api/v1/health` | 상세 헬스체크 |
| `POST` | `/api/v1/routines` | 운동 루틴 추천 |


## 헬스체크

```bash
curl http://localhost:8000/api/v1/health
```



## POST /api/v1/routines

사용자 설문 데이터를 기반으로 맞춤형 운동 루틴을 추천합니다.

### Request Body

<details>
<summary>v1 Request</summary>

```json
{
    "userId": "user_12345",
    "routineCount": 1,
    "survey": [
        {
            "questionContent": "최근 1주일 동안, 목 부위의 불편함이나 통증은 어느 정도였나요?",
            "selectedOptionSortOrder": 4
        },
        {
            "questionContent": "최근 1주일 동안, 어깨 부위에 뻐근함이나 통증을 느낀 정도는 어느 정도였나요?",
            "selectedOptionSortOrder": 3
        },
        {
            "questionContent": "최근 1주일 동안, 허리(요추) 부위의 불편함이나 통증은 어느 정도였나요?",
            "selectedOptionSortOrder": 2
        },
        {
            "questionContent": "최근 1주일 동안, 손목 사용 시 불편함이나 부담을 느낀 정도는 어느 정도였나요?",
            "selectedOptionSortOrder": 3
        },
        {
            "questionContent": "최근 1주일 동안, 하루 평균 장시간 앉아서 보내는 시간은 어느 정도였나요?",
            "selectedOptionSortOrder": 5
        },
        {
            "questionContent": "최근 1주일 동안, 전반적인 신체 피로감은 어느 정도였나요?",
            "selectedOptionSortOrder": 4
        }
    ]
}
```
</details>


#### Request Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `surveyData` | object | ✓ | 사용자 설문 데이터 |
| `surveyData.routineCount` | int | ✓ | 원하는 루틴 개수 (≥0) |
| `surveyData.survey` | array | ✓ | 설문 응답 리스트 |
| `surveyData.survey[].questionContent` | string | ✓ | 설문 문항 내용 |
| `surveyData.survey[].selectedOptionSortOrder` | int | ✓ | 선택한 응답의 정렬 순서 (≥1, ≤5) |

### Response Body

<details>
<summary>v1 Response</summary>

```json
{
    "taskId": "9f3a2c1b-7c1e-4a6b-9d3a-2c1b7c1e4a6b",
    "status": "COMPLETED",
    "progress": 100,
    "currentStep": "운동 플랜 추천 완료!",
    "summary": {
        "totalRoutines": 1,
        "totalExercises": 2
    },
    "errorMessage": null,
    "completedAt": "2026-01-06T15:42:10Z",
    "routines": [
        {
            "routineOrder": 1,
            "reason": "아침 워밍업 루틴으로 목 건강을 최우선으로 고려하여 허리와 어깨를 보조적으로 구성했어요.",
            "steps": [
                {
                    "exerciseId": "001",
                    "type": "DURATION",
                    "stepOrder": 1,
                    "limitTime": 30,
                    "durationTime": 10,
                    "targetReps": null
                },
                {
                    "exerciseId": "002",
                    "type": "REPS",
                    "stepOrder": 2,
                    "limitTime": 30,
                    "durationTime": null,
                    "targetReps": 10
                }
            ]
        }
    ]
}
```
</details>


#### Response Schema

| Field | Type | Description |
|-------|------|-------------|
| `taskId` | string | 추천 태스크 ID |
| `status` | enum | 태스크 상태: `IN_PROGRESS`, `COMPLETED`, `FAILED` |
| `progress` | int | 진행률 (0~100) |
| `currentStep` | string | 현재 처리 단계 설명 |
| `summary` | object \| null | 추천 결과 요약 (완료 시 제공) |
| `summary.totalRoutines` | int | 추천된 루틴 개수 |
| `summary.totalExercises` | int | 전체 운동 개수 |
| `completedAt` | datetime \| null | 태스크 완료 시각 (UTC) |
| `routines` | array \| null | 추천된 루틴 목록 (완료 시 제공) |
| `routines[].routineOrder` | int | 루틴 순서 (≥1) |
| `routines[].reason` | string | 루틴 구성 이유 |
| `routines[].steps` | array | 루틴에 포함된 운동 스텝 목록 |
| `routines[].steps[].exerciseId` | string | 운동 ID |
| `routines[].steps[].type` | enum | 운동 수행 방식: `REPS`, `DURATION` |
| `routines[].steps[].stepOrder` | int | 루틴 내 순서 (≥1) |
| `routines[].steps[].limitTime` | int | 해당 스텝 제한 시간(초) |
| `routines[].steps[].durationTime` | int \| null | 지속 시간 기반 운동일 경우 수행 시간(초) |
| `routines[].steps[].targetReps` | int \| null | 횟수 기반 운동일 경우 목표 반복 횟수 |
| `errorMessage` | string \| null | 실패 시 에러 메시지 |



#### Progress Steps (v1)

| status | progress | currentStep |
|--------|----------|-------------|
| `IN_PROGRESS` | 60 | AI가 최적의 루틴 구성 중 |
| `IN_PROGRESS` | 75 | 최종 추천 결과 검증 중 |
| `COMPLETED` | 100 | 운동 플랜 추천 완료! |