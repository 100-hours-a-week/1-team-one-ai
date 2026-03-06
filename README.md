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

# 환경변수 설정 (환경에 맞는 파일 복사 후 값 입력)
cp .env.example .env.dev   # 개발 환경
cp .env.example .env.stage # 스테이지 환경
cp .env.example .env.prod  # 프로덕션 환경

# 서버 실행 (APP_ENV로 환경 선택)
APP_ENV=dev uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 환경 파일 로딩 규칙

`APP_ENV` 값에 따라 `.env` → `.env.{APP_ENV}` 순서로 파일을 로드합니다.
나중에 로드된 값이 앞의 값을 덮어씁니다.

| `APP_ENV` | 로드 파일 |
|-----------|----------|
| `dev` | `.env` → `.env.dev` |
| `stage` | `.env` → `.env.stage` |
| `prod` | `.env` → `.env.prod` |

## 환경변수

| 변수 | 설명 | 기본값 | 필수 |
|-----|-----|------|-----|
| `HOST` | 서버 호스트 | `0.0.0.0` | X |
| `PORT` | 서버 포트 | `8000` | X |
| `APP_ENV` | 실행 환경 (`dev` / `stage` / `prod`) | `dev` | X |
| `OPENAI_API_KEY` | OPENAI API 키 | - | O |
| `GEMINI_API_KEY` | GEMINI API 키 | - | O |
| `OLLAMA_API_KEY` | OLLAMA API 키 | - | O |
| `LLM_BASE_URL` | LLM API Base URL (Ollama 등) | - | O |
| `API_KEY` | 서비스 인증 키 | - | O |
| `CALLBACK_URL` | 추천 결과 Callback API URL | - (dev: 미사용) | O (stage/prod) |
| `EXERCISE_API_URL` | 운동 데이터 API URL | - | O |
| `EXERCISES_PATH` | exercises.json 저장 경로 | `app/data/exercises.json` | X |
| `LOG_LEVEL` | 로그 레벨 | `DEBUG` (dev), `INFO` (stage/prod) | X |
| `LOG_DIR` | 로그 파일 저장 디렉토리 | `logs/` | X |
| `LOG_FILE_NAME` | 로그 파일 이름 | `app.log` | X |
| `METRICS_ENABLED` | Prometheus 메트릭 활성화 | `true` (dev), `false` (stage/prod) | X |

### 환경별 기본값

| 변수 | dev | stage | prod |
|------|-----|-------|------|
| `APP_ENV` | `dev` | `stage` | `prod` |
| `LOG_LEVEL` | `DEBUG` | `DEBUG` | `INFO` |
| `METRICS_ENABLED` | `true` | `false` | `false` |
| `CALLBACK_URL` | (비활성) | `https://stage.raisedeveloper.com/...` | `https://raisedeveloper.com/...` |
| `EXERCISE_API_URL` | `https://dev.raisedeveloper.com/...` | `https://stage.raisedeveloper.com/...` | `https://raisedeveloper.com/...` |


## API 엔드포인트

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | 헬스체크 |
| `GET` | `/api/v1/health` | 상세 헬스체크 |
| `POST` | `/api/v1/routines` | 운동 루틴 추천 (동기) |
| `POST` | `/api/v1/exercises/update` | 운동 데이터 강제 업데이트 |
| `POST` | `/api/v2/routines` | 운동 루틴 추천 (비동기, 202 즉시 반환) |
| `GET` | `/api/v2/routines/{task_id}` | 추천 태스크 상태 폴링 |
| `POST` | `/api/v2/exercises/update` | 운동 데이터 강제 업데이트 (v2) |


### GET /api/v1/health
상세 헬스체크

```bash
curl http://localhost:8000/api/v1/health
```


### POST /api/v1/exercises/update
운동 데이터 강제 업데이트 & 로드

```bash
curl -X POST http://localhost:8000/api/v1/exercises/update
```

#### Response

```json
{
    "status": "ok",
    "count": 42
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | 처리 결과 (`ok`) |
| `count` | int | 로드된 운동 데이터 개수 |


### POST /api/v1/routines

사용자 설문 데이터를 기반으로 맞춤형 운동 루틴을 추천합니다.

#### Request Body

<details>
<summary>v1 Request</summary>

```json
{
    "userId": 1,
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

#### Response Body

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
                    "id": "001",
                    "type": "DURATION",
                    "stepOrder": 1,
                    "limitTime": 30,
                    "durationTime": 10,
                    "targetReps": null
                },
                {
                    "id": "002",
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



### POST /api/v2/routines

사용자 설문 데이터를 기반으로 맞춤형 운동 루틴을 추천합니다.
v1과 달리 202를 즉시 반환하고 백그라운드에서 처리 후 Callback / Polling으로 결과를 전달합니다.

#### Request Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `taskId` | string | ✓ | coreBE에서 생성한 태스크 ID |
| `userId` | int | ✓ | 사용자 ID |
| `surveyData` | object | ✓ | 사용자 설문 데이터 |
| `surveyData.routineCount` | int | ✓ | 원하는 루틴 개수 (≥1) |
| `surveyData.survey` | array | ✓ | 설문 응답 리스트 |
| `surveyData.survey[].questionContent` | string | ✓ | 설문 문항 내용 |
| `surveyData.survey[].selectedOptionSortOrder` | int | ✓ | 선택한 응답의 정렬 순서 (1~5) |

<details>
<summary>v2 Request 예시</summary>

```json
{
    "taskId": "task-id-1234",
    "userId": 1,
    "surveyData": {
        "routineCount": 4,
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
            },
            {
                "questionContent": "최근 1주일 동안, 화면을 오래 본 후 눈의 피로감이나 시각적 불편함을 느낀 정도는 어느 정도였나요?",
                "selectedOptionSortOrder": 5
            }
        ]
    }
}
```
</details>

#### Response (202 즉시 반환)

<details>
<summary>v2 POST Response (TaskAcceptedResponse)</summary>

```json
{
    "taskId": "task-id-1234",
    "userId": 1,
    "status": "IN_PROGRESS",
    "progress": 0,
    "currentStep": "AI가 최적의 루틴 구성 중"
}
```
</details>

| Field | Type | Description |
|-------|------|-------------|
| `taskId` | string | 추천 태스크 ID |
| `userId` | int | 사용자 ID |
| `status` | enum | `IN_PROGRESS` (항상) |
| `progress` | int | 진행률 (0) |
| `currentStep` | string | 현재 처리 단계 설명 |


### GET /api/v2/routines/{task_id}

태스크 상태를 폴링합니다. Callback과 동일한 응답 스키마를 반환합니다.

#### Response (Callback / Polling 동일)

<details>
<summary>v2 완료 Response (TaskResult)</summary>

```json
{
    "taskId": "task-id-1234",
    "userId": 1,
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
            "reason": "아침 워밍업 루틴으로 목 건강을 최우선으로 고려하여 허리와 어깨를 보조적으로 구성",
            "steps": [
                {
                    "exerciseId": 60,
                    "type": "DURATION",
                    "stepOrder": 1,
                    "limitTime": 30,
                    "durationTime": 10,
                    "targetReps": null,
                    "side": null
                },
                {
                    "exerciseId": 51,
                    "type": "REPS",
                    "stepOrder": 2,
                    "limitTime": 30,
                    "durationTime": null,
                    "targetReps": 10,
                    "side": "left"
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
| `userId` | int | 사용자 ID |
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
| `routines[].steps[].exerciseId` | int | 운동 ID |
| `routines[].steps[].type` | enum | 운동 수행 방식: `REPS`, `DURATION`, `EYES` |
| `routines[].steps[].stepOrder` | int | 루틴 내 순서 (≥1) |
| `routines[].steps[].limitTime` | int | 해당 스텝 제한 시간(초) |
| `routines[].steps[].durationTime` | int \| null | 지속 시간 기반 운동일 경우 수행 시간(초) |
| `routines[].steps[].targetReps` | int \| null | 횟수 기반 운동일 경우 목표 반복 횟수 |
| `routines[].steps[].side` | string \| null | 좌우 방향: `left`, `right` (양측 운동) |
| `errorMessage` | string \| null | 실패 시 에러 메시지 |

#### Progress Steps (v2)

| status | progress | currentStep |
|--------|----------|-------------|
| `IN_PROGRESS` | 10 | 건강 점수 계산 중 |
| `IN_PROGRESS` | 25 | 카테고리 우선순위 분석 중 |
| `IN_PROGRESS` | 40 | 운동 데이터 검색 중 |
| `IN_PROGRESS` | 60 | AI가 최적의 루틴 구성 중 |
| `IN_PROGRESS` | 75 | 최종 추천 결과 검증 중 |
| `COMPLETED` | 100 | 운동 플랜 추천 완료! |
| `FAILED` | 0 | (errorMessage 포함) |

