# Recommendation API

추천 서비스 백엔드 API

## 요구사항

- Python 3.11
- Docker (배포 시)

## 로컬 실행

```bash
# 의존성 설치
pip install -r requirements.txt

# 환경변수 설정
cp .env.example .env

# 서버 실행
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 환경변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `HOST` | 서버 호스트 | `0.0.0.0` |
| `PORT` | 서버 포트 | `8000` |
| `LLM_API_URL` | LLM API 엔드포인트 | - |
| `LLM_API_KEY` | LLM API 키 | - |

## API 엔드포인트

- `GET /api/v1/health` - 헬스체크
- `POST /api/v1/recommend` - 추천 요청

## 헬스체크

```bash
curl http://localhost:8000/api/v1/health
```

## 프로젝트 구조

```
app/
├── main.py              # FastAPI 엔트리포인트
├── api/v1/              # API 라우터
├── core/                # 설정, 로깅, 예외
├── schemas/             # Pydantic 모델
├── services/            # 비즈니스 로직
└── utils/               # 유틸리티
```
