# Recommendation API

사무직 사용자를 위한 AI 기반 맞춤형 운동 루틴 추천 백엔드 API입니다.

사용자의 건강 설문 응답, 과거 운동 활동 이력, 만족도 피드백을 복합적으로 분석하여 개인화된 운동 루틴을 생성합니다. 목, 어깨, 허리, 손목, 눈 등 신체 부위별 불편함 정도를 고려한 추천이 핵심입니다.

---

## 목차

- [시스템 개요](#시스템-개요)
- [추천 엔진 버전별 설명](#추천-엔진-버전별-설명)
- [기술 스택](#기술-스택)
- [요구사항](#요구사항)
- [로컬 실행](#로컬-실행)
- [환경변수](#환경변수)
- [LLM 설정](#llm-설정)
- [API 엔드포인트](#api-엔드포인트)
  - [공통 스키마](#공통-스키마)
  - [V1 API](#v1-api-동기-추천)
  - [V2 API](#v2-api-비동기-추천--벡터-검색)
  - [V3 API](#v3-api-비동기-추천--협업-필터링)
- [데이터 흐름](#데이터-흐름)
- [Graceful Degradation](#graceful-degradation)
- [아키텍처](#아키텍처)
- [테스트](#테스트)

---

## 시스템 개요

이 서버는 **Core Backend (coreBE)** 서버와 협력하여 동작합니다.

- coreBE는 운동 데이터와 사용자 활동 이력을 이 서버에 주기적으로 전송합니다.
- 사용자가 헬스 설문을 완료하면, coreBE가 이 서버에 추천을 요청합니다.
- 추천 결과는 **Callback (Push)** 또는 **Polling (Pull)** 방식으로 coreBE에 전달됩니다.

```
coreBE
  ├── POST /api/v*/update/exercises    →  운동 데이터 동기화
  ├── POST /api/v2/update/users        →  사용자 활동 프로필 동기화
  ├── POST /api/v3/update/satisfaction →  만족도 피드백 동기화
  └── POST /api/v*/routines            →  추천 요청
          ↓ (비동기 완료 후)
      Callback → coreBE
      또는 GET /api/v*/routines/{task_id} (폴링)
```

---

## 추천 엔진 버전별 설명

| 버전 | 추천 방식 | 응답 방식 | 특징 |
|------|-----------|-----------|------|
| **V1** | LLM 기반 | 동기 (즉시 반환) | exercises.json 전체를 LLM 프롬프트에 포함 |
| **V2** | 벡터 검색 + LLM fallback | 비동기 (202 → Callback/Polling) | Qdrant 벡터 유사도 검색, 활동 프로필 블렌딩 |
| **V3** | 협업 필터링 + 벡터 + LLM fallback | 비동기 (202 → Callback/Polling) | 만족도 Sparse Vector 기반 CF 혼합 |

### 추천 경로 자동 선택 (Graceful Degradation)

모든 버전은 인프라 상태에 따라 자동으로 최선의 추천 경로를 선택합니다.

```
Qdrant 연결 O → 벡터/CF 기반 추천
Qdrant 연결 X → LLM 기반 추천
LLM 오류      → Rule-based 추천 (항상 동작)
```

---

## 기술 스택

| 구분 | 기술 |
|------|------|
| 언어 | Python 3.11 |
| 프레임워크 | FastAPI |
| 패키지 관리 | uv |
| Lint / Format | Ruff |
| 벡터 DB | Qdrant |
| 임베딩 모델 | `intfloat/multilingual-e5-base` (기본값, 변경 가능) |
| LLM | OpenAI, Ollama (cloud/self-hosted), Gemini |
| HTTP 클라이언트 | httpx |
| 유효성 검사 | Pydantic v2 |
| 메트릭 | Prometheus (FastAPI Instrumentator) |

---

## 요구사항

- Python 3.11.x
- [uv](https://docs.astral.sh/uv/) (패키지 매니저)
- Qdrant (벡터 검색 사용 시 — 없어도 LLM fallback으로 동작)
- LLM API 키 (OpenAI 또는 Ollama 등)

---

## 로컬 실행

```bash
# 1. 의존성 설치 (uv 사용 — pip, poetry 등 사용 금지)
uv sync

# 2. 환경변수 설정
cp .env.example .env.dev
# .env.dev 파일을 열어 필요한 값 입력 (아래 환경변수 섹션 참고)

# 3. 서버 실행
APP_ENV=dev uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# 4. API 문서 확인 (개발 환경 자동 활성화)
# http://localhost:8000/docs
```

### Qdrant 로컬 실행 (Docker)

벡터 검색 기능을 로컬에서 테스트하려면 Qdrant를 실행합니다. Qdrant 없이도 LLM fallback으로 동작합니다.

```bash
docker run -p 6333:6333 qdrant/qdrant
```

### 환경 파일 로딩 규칙

`APP_ENV` 값에 따라 `.env` → `.env.{APP_ENV}` 순서로 로드하며, 나중 파일이 앞 파일을 덮어씁니다.

| `APP_ENV` | 로드 파일 |
|-----------|----------|
| `dev` | `.env` → `.env.dev` |
| `stage` | `.env` → `.env.stage` |
| `prod` | `.env` → `.env.prod` |

---

## 환경변수

`.env.example`을 복사하여 사용합니다.

| 변수 | 설명 | 기본값 | 필수 |
|------|------|--------|------|
| `APP_ENV` | 실행 환경 (`dev` / `stage` / `prod`) | `dev` | X |
| `HOST` | 서버 호스트 | `0.0.0.0` | X |
| `PORT` | 서버 포트 | `8000` | X |
| `LOG_LEVEL` | 로그 레벨 (`DEBUG` / `INFO`) | `INFO` | X |
| `LOG_DIR` | 로그 파일 저장 디렉토리 | `logs/` | X |
| `LOG_FILE_NAME` | 로그 파일 이름 | `app.log` | X |
| `METRICS_ENABLED` | Prometheus 메트릭 활성화 | `false` | X |
| `OPENAI_API_KEY` | OpenAI API 키 | — | LLM에 따라 |
| `GEMINI_API_KEY` | Gemini API 키 | — | LLM에 따라 |
| `OLLAMA_API_KEY` | Ollama API 키 | — | LLM에 따라 |
| `EXERCISE_API_URL` | coreBE 운동 데이터 API URL | — | O |
| `CALLBACK_URL` | 추천 결과 Callback URL (coreBE) | — (dev: 미사용) | stage/prod |
| `EXERCISES_PATH` | exercises.json 저장 경로 | `app/data/exercises.json` | X |
| `QDRANT_URL` | Qdrant 서버 URL | `http://localhost:6333` | X |
| `QDRANT_API_KEY` | Qdrant API 키 (cloud 전용) | — | X |
| `QDRANT_EMBEDDING_MODEL` | 임베딩 모델 HuggingFace ID | `intfloat/multilingual-e5-base` | X |

### 환경별 기본값 차이

| 변수 | dev | stage | prod |
|------|-----|-------|------|
| `LOG_LEVEL` | `DEBUG` | `DEBUG` | `INFO` |
| `METRICS_ENABLED` | `true` | `false` | `false` |
| `CALLBACK_URL` | 비활성 | stage URL | prod URL |
| `EXERCISE_API_URL` | dev URL | stage URL | prod URL |

---

## LLM 설정

LLM 프로바이더는 `app/configs/llm.yaml`에서 설정합니다.

```yaml
default_provider: ollama_cloud   # 사용할 프로바이더 키

providers:
  openai:
    spec: openai_compatible
    auth: api_key
    base_url: https://api.openai.com/v1
    model: gpt-4.1-mini
    timeout_sec: 40
    max_tries: 1

  ollama_cloud:
    spec: openai_compatible
    auth: api_key
    base_url: https://ollama.com
    model: gpt-oss:120b-cloud
    timeout_sec: 40
    max_tries: 1

  gemini:
    spec: gemini_native
    auth: api_key
    model: gemini-2.5-flash
    timeout_sec: 40
    max_tries: 1

  self_hosted:
    spec: openai_compatible
    auth: none
    base_url: http://localhost:11434
    model: gemma3:12b
    timeout_sec: 40
    max_tries: 1

fallback: true   # LLM 실패 시 rule-based fallback 활성화
```

- `default_provider` 값만 바꾸면 프로바이더를 교체할 수 있습니다.
- `fallback: true`이면 LLM 오류 시 rule-based 추천으로 자동 전환됩니다.

---

## API 엔드포인트

### 전체 엔드포인트 목록

| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/` | 기본 헬스체크 |
| `GET` | `/api/v1/health` | V1 상세 헬스체크 (exercises 상태) |
| `POST` | `/api/v1/routines` | 운동 루틴 추천 (동기) |
| `POST` | `/api/v1/exercises/update` | 운동 데이터 강제 업데이트 |
| `GET` | `/api/v2/health` | V2 상세 헬스체크 (exercises + Qdrant 상태) |
| `POST` | `/api/v2/routines` | 운동 루틴 추천 (비동기, 202) |
| `GET` | `/api/v2/routines/{task_id}` | 추천 태스크 상태 폴링 |
| `POST` | `/api/v2/update/exercises` | 운동 데이터 업데이트 + 벡터 upsert |
| `POST` | `/api/v2/update/users` | 사용자 활동 프로필 배치 upsert |
| `GET` | `/api/v2/diagnostics/qdrant` | Qdrant 컬렉션 전체 상태 조회 |
| `GET` | `/api/v2/diagnostics/qdrant/{collection_name}` | Qdrant 특정 컬렉션 상태 조회 |
| `POST` | `/api/v3/routines` | 운동 루틴 추천 (비동기, CF 혼합, 202) |
| `GET` | `/api/v3/routines/{task_id}` | 추천 태스크 상태 폴링 |
| `POST` | `/api/v3/update/satisfaction` | 사용자 만족도 배치 upsert |

---

### 공통 스키마

#### SurveyAnswer

설문 응답 항목 하나를 나타냅니다.

| Field | Type | 설명 |
|-------|------|------|
| `questionContent` | string | 설문 문항 내용 |
| `selectedOptionSortOrder` | int (1~5) | 선택한 응답의 정렬 순서 (1=거의 없음, 5=매우 심함) |

#### RoutineStep

추천 루틴 내 운동 스텝 하나를 나타냅니다.

| Field | Type | 설명 |
|-------|------|------|
| `exerciseId` | int | 운동 ID |
| `type` | `REPS` \| `DURATION` \| `EYES` | 운동 수행 방식 |
| `stepOrder` | int | 루틴 내 순서 (1부터 시작) |
| `limitTime` | int | 해당 스텝 제한 시간 (초) |
| `durationTime` | int \| null | 지속 시간 기반 운동의 수행 시간 (초) |
| `targetReps` | int \| null | 횟수 기반 운동의 목표 반복 횟수 |
| `side` | `left` \| `right` \| null | 좌우 방향 (양측 운동의 경우) |

#### ProgressStep (V2+)

| `progress` | `currentStep` |
|------------|---------------|
| 0 | (FAILED 상태) |
| 10 | 건강 점수 계산 중 |
| 25 | 카테고리 우선순위 분석 중 |
| 40 | 운동 데이터 검색 중 |
| 60 | AI가 최적의 루틴 구성 중 |
| 75 | 최종 추천 결과 검증 중 |
| 100 | 운동 플랜 추천 완료! |

---

### V1 API (동기 추천)

#### `POST /api/v1/routines`

사용자 설문 데이터를 기반으로 운동 루틴을 동기 방식으로 추천합니다. exercises.json 전체를 LLM 프롬프트에 포함하여 추천을 생성합니다.

**Request**

| Field | Type | Required | 설명 |
|-------|------|----------|------|
| `userId` | int | O | 사용자 ID |
| `surveyData.routineCount` | int (≥1) | O | 원하는 루틴 개수 |
| `surveyData.survey` | SurveyAnswer[] | O | 설문 응답 목록 |

<details>
<summary>Request 예시</summary>

```json
{
    "userId": 1,
    "surveyData": {
        "routineCount": 2,
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
}
```
</details>

**Response (200)**

| Field | Type | 설명 |
|-------|------|------|
| `taskId` | string | 추천 태스크 ID |
| `status` | `COMPLETED` \| `FAILED` | 태스크 상태 |
| `progress` | int | 진행률 (100 = 완료) |
| `currentStep` | string | 현재 처리 단계 설명 |
| `summary.totalRoutines` | int | 추천된 루틴 수 |
| `summary.totalExercises` | int | 전체 운동 수 |
| `completedAt` | datetime \| null | 완료 시각 (UTC) |
| `routines` | Routine[] \| null | 추천 루틴 목록 |
| `errorMessage` | string \| null | 실패 시 에러 메시지 |

<details>
<summary>Response 예시</summary>

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
            "reason": "목 건강을 최우선으로 고려하여 허리와 어깨를 보조적으로 구성했어요.",
            "steps": [
                {
                    "exerciseId": 51,
                    "type": "DURATION",
                    "stepOrder": 1,
                    "limitTime": 30,
                    "durationTime": 10,
                    "targetReps": null,
                    "side": null
                },
                {
                    "exerciseId": 60,
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

---

#### `POST /api/v1/exercises/update`

coreBE에서 운동 데이터를 가져와 로컬에 저장합니다.

```bash
curl -X POST http://localhost:8000/api/v1/exercises/update
```

**Response (200)**

```json
{
    "status": "ok",
    "count": 42
}
```

---

### V2 API (비동기 추천 + 벡터 검색)

V2는 추천을 비동기로 처리합니다. POST 요청 시 즉시 202를 반환하고, 백그라운드에서 추천을 수행한 후 결과를 콜백으로 전송하거나 폴링으로 조회할 수 있습니다.

Qdrant 연결 여부에 따라 추천 경로가 자동 선택됩니다.
- **Qdrant 연결 O**: 벡터 검색 기반 추천 (설문 벡터 + 활동 벡터 블렌딩)
- **Qdrant 연결 X**: LLM 기반 추천으로 fallback

#### `POST /api/v2/routines`

**Request**

| Field | Type | Required | 설명 |
|-------|------|----------|------|
| `taskId` | string | O | coreBE에서 생성한 태스크 ID |
| `userId` | int | O | 사용자 ID |
| `surveyData.routineCount` | int (≥1) | O | 원하는 루틴 개수 |
| `surveyData.survey` | SurveyAnswer[] | O | 설문 응답 목록 |

<details>
<summary>Request 예시</summary>

```json
{
    "taskId": "task-id-1234",
    "userId": 1,
    "surveyData": {
        "routineCount": 2,
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

**Response (202)**

```json
{
    "taskId": "task-id-1234",
    "userId": 1,
    "status": "IN_PROGRESS",
    "progress": 0,
    "currentStep": "AI가 최적의 루틴 구성 중"
}
```

---

#### `GET /api/v2/routines/{task_id}`

태스크 상태를 폴링합니다. 콜백 응답과 동일한 스키마를 반환합니다.

**Response**

| Field | Type | 설명 |
|-------|------|------|
| `taskId` | string | 추천 태스크 ID |
| `userId` | int | 사용자 ID |
| `status` | `IN_PROGRESS` \| `COMPLETED` \| `FAILED` | 태스크 상태 |
| `progress` | int | 진행률 (0~100) |
| `currentStep` | string | 현재 처리 단계 |
| `summary` | object \| null | 추천 결과 요약 (완료 시 제공) |
| `completedAt` | datetime \| null | 완료 시각 (UTC) |
| `routines` | Routine[] \| null | 추천 루틴 목록 (완료 시 제공) |
| `errorMessage` | string \| null | 실패 시 에러 메시지 |

<details>
<summary>Response 예시 (COMPLETED)</summary>

```json
{
    "taskId": "task-id-1234",
    "userId": 1,
    "status": "COMPLETED",
    "progress": 100,
    "currentStep": "운동 플랜 추천 완료!",
    "summary": {
        "totalRoutines": 2,
        "totalExercises": 8
    },
    "errorMessage": null,
    "completedAt": "2026-01-06T15:42:10Z",
    "routines": [
        {
            "routineOrder": 1,
            "reason": "목 부위 통증 완화를 최우선으로, 어깨와 눈의 피로도 함께 고려하여 구성했어요.",
            "steps": [
                {
                    "exerciseId": 51,
                    "type": "DURATION",
                    "stepOrder": 1,
                    "limitTime": 30,
                    "durationTime": 10,
                    "targetReps": null,
                    "side": null
                },
                {
                    "exerciseId": 60,
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

---

#### `POST /api/v2/update/exercises`

coreBE에서 운동 데이터를 가져와 로컬에 저장하고 Qdrant에 벡터 upsert합니다. Qdrant 미연결 시 저장만 수행하고 200을 반환합니다.

```bash
curl -X POST http://localhost:8000/api/v2/update/exercises
```

---

#### `POST /api/v2/update/users`

coreBE로부터 사용자 활동 프로필 배치를 수신하여 Qdrant에 벡터 upsert합니다. Non-cold start 판단에 사용됩니다.

**Request**

```json
{
    "profiles": [
        {
            "userId": 1,
            "bodyPartRatios": {
                "neck": 0.4,
                "shoulder": 0.3,
                "wrist": 0.0,
                "lowerBack": 0.2,
                "eyes": 0.1
            },
            "exerciseTypeRatios": {
                "DURATION": 0.6,
                "REPS": 0.25,
                "EYES": 0.15
            },
            "difficultyRatios": {
                "1": 0.2,
                "2": 0.65,
                "3": 0.15
            },
            "weeklyFrequency": 4
        }
    ]
}
```

| Field | Type | 설명 |
|-------|------|------|
| `userId` | int | 사용자 ID |
| `bodyPartRatios` | object | 신체 부위별 운동 비율 |
| `exerciseTypeRatios` | object | 운동 유형별 비율 (DURATION / REPS / EYES) |
| `difficultyRatios` | object | 난이도별 비율 (1 / 2 / 3) |
| `weeklyFrequency` | int | 주간 운동 빈도 |

---

#### `GET /api/v2/diagnostics/qdrant`

Qdrant 컬렉션 전체 상태를 조회합니다.

```bash
curl http://localhost:8000/api/v2/diagnostics/qdrant
```

**Response 예시**

```json
{
    "collections": {
        "exercises": {
            "exists": true,
            "points_count": 42,
            "updated_at": "2026-01-06T10:00:00Z"
        },
        "user_activity_profiles": {
            "exists": true,
            "points_count": 150,
            "updated_at": "2026-01-06T09:00:00Z"
        }
    }
}
```

---

### V3 API (비동기 추천 + 협업 필터링)

V3는 사용자 만족도 피드백을 Sparse Vector로 표현하여 협업 필터링(CF)과 벡터 검색을 혼합합니다.

- **Qdrant 연결 O**: CF 혼합 경로 (만족도 데이터 있으면 CF + 벡터, 없으면 벡터만)
- **Qdrant 연결 X**: LLM 기반 추천으로 fallback

Request / Response 스키마는 V2와 동일합니다.

---

#### `POST /api/v3/update/satisfaction`

coreBE로부터 사용자 운동 만족도 데이터를 수신하여 Qdrant에 Sparse Vector로 upsert합니다.

> **배치 시맨틱**: Full Snapshot (덮어쓰기)
> `records`에 포함된 `userId`의 만족도를 Qdrant에 전량 덮어씁니다. 일부만 전송하면 기존 데이터가 소실됩니다.

**Request**

```json
{
    "records": [
        {
            "userId": 1,
            "exerciseId": 51,
            "satisfaction": 1
        },
        {
            "userId": 1,
            "exerciseId": 60,
            "satisfaction": -1
        }
    ]
}
```

| Field | Type | 설명 |
|-------|------|------|
| `userId` | int | 사용자 ID |
| `exerciseId` | int | 운동 ID |
| `satisfaction` | `1` \| `-1` | 만족도 (+1: 좋아요, -1: 싫어요) |

**Response**

```json
{
    "status": "ok",
    "upserted": 2
}
```

---

## 데이터 흐름

### 운동 데이터 동기화

```
coreBE
  └─ POST /api/v2/update/exercises
        ├─ app/data/loader.py: coreBE API 호출 → exercises.json 저장
        └─ ExerciseVectorService.try_upsert_all()
              ├─ passage 생성: "passage: 운동명: {name} | 부위: {bodyPart} | 효과: {effect} | 태그: {tags}"
              └─ Qdrant "exercises" 컬렉션에 벡터 upsert
```

### V2 비동기 추천 흐름

```
[요청 접수]
Client → POST /api/v2/routines
              ├─ TaskService.create_task()  →  InMemoryTaskStore (taskId 즉시 반환 202)
              └─ BackgroundTask 실행

[백그라운드 처리]
VectorRecommendService
  ├─ 설문 쿼리 생성: "query: 건강 상태: {증상들} | 목표: {목표}"
  ├─ embedding_model.encode(query) → survey_vector
  ├─ [Non-cold start] activity_vector 조회 → blended = 0.4*survey + 0.6*activity
  └─ Qdrant "exercises" 검색 → RoutineList 구성

V2ResponseBuilder → TaskResult 생성
TaskStore.update(COMPLETED)
CallbackClient → coreBE에 결과 POST

[결과 조회]
Client → GET /api/v2/routines/{taskId} → TaskResult
```

### Cold Start 판단

사용자의 Qdrant 활동 프로필 존재 여부로 Cold Start를 판단합니다.

| 상태 | 쿼리 벡터 |
|------|-----------|
| Cold Start (신규 사용자) | survey_vector만 사용 |
| Non-cold Start (기존 사용자) | `0.4 × survey_vector + 0.6 × activity_vector` |

---

## Graceful Degradation

인프라 장애 상황에서도 서비스가 최대한 동작합니다.

| 상황 | 동작 |
|------|------|
| Qdrant 미연결 | 벡터 upsert silent skip, API 200 반환 (error_type 포함) |
| 벡터 검색 실패 | Rule-based 추천 fallback |
| Cold start 판단 실패 | 안전하게 Cold start=True로 처리 (설문 벡터만 사용) |
| 임베딩 모델 로딩 실패 | 벡터 서비스 None, upsert skip |
| LLM 오류 | Rule-based 추천 fallback |
| 헬스 상태 | 최대 `DEGRADED` — `UNHEALTHY` 없음 (Rule-based 추천은 항상 가능) |

---

## 아키텍처

### 디렉토리 구조

```
app/
├── main.py                         # FastAPI 앱 생성, 로깅/예외 핸들러, Prometheus
├── api/                            # API 레이어 (엔드포인트 + 라우터)
│   ├── deps.py                     # 중앙 DI 모듈 (싱글턴 + per-request 팩토리)
│   ├── v1/
│   │   ├── health.py               # GET /api/v1/health
│   │   ├── recommend.py            # POST /api/v1/routines
│   │   └── data.py                 # POST /api/v1/exercises/update
│   ├── v2/
│   │   ├── health.py               # GET /api/v2/health
│   │   ├── recommend.py            # POST /api/v2/routines, GET /api/v2/routines/{id}
│   │   ├── data.py                 # POST /api/v2/update/exercises, /update/users
│   │   └── diagnostics.py          # GET /api/v2/diagnostics/qdrant
│   └── v3/
│       ├── recommend.py            # POST /api/v3/routines, GET /api/v3/routines/{id}
│       └── data.py                 # POST /api/v3/update/satisfaction
│
├── domain/                         # 순수 비즈니스 엔티티 (외부 의존성 없음)
│   ├── exercise.py                 # BaseExercise, ExerciseType, DifficultyLevel, BodyPart
│   ├── routine.py                  # RoutineStep, Routine, RoutineList
│   └── routinestep_factory.py      # Exercise → RoutineStep 변환
│
├── schemas/                        # Pydantic 모델 (API 계약)
│   ├── common.py                   # 공통 Enum, ErrorResponse, SurveyAnswer
│   ├── v1/                         # V1 request/response
│   ├── v2/                         # V2 request/response/task/user_activity
│   └── v3/                         # V3 request/response/satisfaction
│
├── services/                       # 비즈니스 로직
│   ├── recommend/
│   │   ├── recommend_service.py    # LLM 기반 추천 (재시도 + fallback)
│   │   ├── vector_recommend_service.py  # 벡터 검색 기반 추천
│   │   ├── cf_recommend_service.py      # 협업 필터링 혼합 추천
│   │   ├── rule_based_recommender.py    # Rule-based 추천 (LLM fallback)
│   │   └── cold_start_checker.py        # ColdStartChecker Protocol + 구현체
│   ├── response/
│   │   ├── base.py                 # CoreResponseBuilder (검증 + 시간 조정)
│   │   ├── v1.py                   # V1ResponseBuilder
│   │   └── v2.py                   # V2ResponseBuilder
│   ├── task/
│   │   ├── service.py              # TaskService (태스크 생명주기)
│   │   ├── store.py                # TaskStore Protocol + InMemoryTaskStore
│   │   └── executor.py             # TaskExecutor Protocol + BackgroundTaskExecutor
│   ├── llm_clients/
│   │   ├── base.py                 # LLMClient Protocol
│   │   ├── openai_client.py        # OpenAI API 클라이언트
│   │   └── ollama_client.py        # Ollama 클라이언트
│   ├── exercise_vector_service.py  # 운동 임베딩 + Qdrant upsert
│   ├── user_activity_vector_service.py  # 사용자 프로필 임베딩 + Qdrant upsert
│   ├── satisfaction_service.py     # 만족도 Sparse Vector + Qdrant upsert
│   └── callback_client.py          # coreBE 콜백 HTTP 클라이언트
│
├── data/                           # 데이터 접근 레이어
│   ├── loader.py                   # ExerciseRepository (exercises.json 싱글턴)
│   ├── exercises.json              # 로컬 운동 데이터
│   ├── qdrant_client.py            # QdrantClient 싱글턴 + 연결 검증
│   ├── qdrant_exceptions.py        # QdrantError 계층 + translate_qdrant_error()
│   ├── exercise_vector_repository.py    # ExerciseVectorRepository Protocol + Qdrant 구현
│   ├── user_activity_repository.py      # UserActivityVectorRepository Protocol + Qdrant 구현
│   └── satisfaction_repository.py       # SatisfactionRepository Protocol + Qdrant 구현
│
├── prompts/                        # LLM 프롬프트 템플릿
│   ├── v1/recommend.py             # V1 SYSTEM_PROMPT, build_user_prompt()
│   └── v2/                         # V2 추천 프롬프트 + reason 생성 프롬프트
│
├── configs/
│   ├── llm.yaml                    # LLM 프로바이더 설정
│   └── llm_config.py               # YAML 로더 + Pydantic 모델
│
└── core/
    ├── config.py                   # Settings (환경변수), RoutineTimePolicy, CallbackPolicy
    ├── logging.py                  # RotatingFileHandler 로깅 설정
    └── exceptions.py               # AppError 계층 + HTTP 핸들러
```

### DI (의존성 주입) 구조

`app/api/deps.py`가 모든 의존성을 중앙 관리합니다.

| 그룹 | 설명 | 예시 |
|------|------|------|
| **싱글턴** | 프로세스 생명주기 동안 1개 인스턴스 유지 | LLM 클라이언트, TaskStore, 임베딩 모델, Callback 클라이언트 |
| **per-request 팩토리** | 매 요청마다 최신 exercises.json 반영 | RecommendService, ResponseBuilder |

### 루틴 시간 정책

`app/core/config.py`의 `RoutineTimePolicy`로 관리됩니다.

| 상수 | 값 | 설명 |
|------|-----|------|
| `MIN_TIME` | 150초 | 루틴 최소 수행 시간 (2분 30초) |
| `MAX_TIME` | 210초 | 루틴 최대 수행 시간 (3분 30초) |
| `TARGET_TIME` | 180초 | 루틴 목표 수행 시간 (3분) |
| `DEFAULT_DURATION_TIME` | 10초 | DURATION 운동 기본 수행 시간 |
| `DEFAULT_TARGET_REPS` | 10회 | REPS 운동 기본 반복 횟수 |

### Qdrant 컬렉션

| 컬렉션 | 소유 파일 | 설명 |
|--------|----------|------|
| `exercises` | `app/data/exercise_vector_repository.py` | 운동 Dense Vector (bodyPart, type, difficulty payload 포함) |
| `user_activity_profiles` | `app/data/user_activity_repository.py` | 사용자 활동 Dense Vector |
| `user_satisfaction` | `app/data/satisfaction_repository.py` | 사용자 만족도 Sparse Vector (CF용) |

---


## 로컬 개발 팁

### 운동 데이터 초기화

서버 최초 실행 시 exercises.json이 없으면 추천이 동작하지 않습니다. 서버 실행 후 아래 요청으로 데이터를 초기화합니다. (요청 전, `.env`의 `EXERCISE_API_URL`이 설정되었는지 확인하세요)

```bash
curl -X POST http://localhost:8000/api/v2/update/exercises
```

### Qdrant 없이 개발하기

Qdrant를 실행하지 않아도 LLM 기반 추천은 동작합니다. Qdrant 관련 기능(벡터 검색, 사용자 활동 프로필)은 silent skip됩니다. `/api/v2/health`에서 Qdrant 연결 상태를 확인할 수 있습니다.

### API 문서

서버 실행 후 자동 생성된 Swagger UI로 API를 탐색할 수 있습니다.

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
