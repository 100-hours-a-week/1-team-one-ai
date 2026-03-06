# ========== Builder Stage (의존성 설치 + 모델 다운로드) ==========
FROM python:3.11-slim AS builder

# uv 설치
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 시스템 의존성 설치 (C 컴파일이 필요한 패키지가 있다면 주석 해제)
#RUN apt-get update && \
#    apt-get install -y --no-install-recommends build-essential && \
#    rm -rf /var/lib/apt/lists/*

# Docker 내부에 가상환경(.venv) 생성
# 컨테이너 안이라도 가상환경을 쓰면 나중에 런타임으로 통째로 복사하기가 쉬워짐
ENV VIRTUAL_ENV=/app/.venv
RUN uv venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# 의존성 파일 복사
COPY pyproject.toml uv.lock ./

# 의존성 설치 (pyproject.toml에 정의된 인덱스 정보를 따름 — torch CPU 전용)
RUN uv sync --frozen --no-dev --no-install-project

# 임베딩 모델 사전 다운로드 (빌드 시 캐싱 → 런타임 HuggingFace 다운로드 불필요)
# 모델명은 config.py의 QDRANT_EMBEDDING_MODEL 기본값과 일치해야 함
ARG EMBEDDING_MODEL=intfloat/multilingual-e5-small
ENV HF_HOME=/app/.cache/huggingface
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"

# ========== Runtime Stage (프로덕션) ==========
FROM python:3.11-slim

WORKDIR /app

# Builder에서 완성된 가상환경(.venv)째로 복사
COPY --from=builder --chown=nobody:nogroup /app/.venv /app/.venv

# [추가] Builder에서 사전 다운로드한 HuggingFace 모델 캐시 복사
COPY --from=builder --chown=nobody:nogroup /app/.cache /app/.cache

# 소스 코드 복사
COPY --chown=nobody:nogroup . .

RUN chown -R nobody:nogroup /app

# 비루트 사용자로 실행
USER nobody

# 환경변수
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
# [추가] 런타임에도 동일한 캐시 경로 사용 (Builder의 HF_HOME과 일치)
ENV HF_HOME=/app/.cache/huggingface

# 포트 노출
EXPOSE 8000

# 애플리케이션 실행
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
