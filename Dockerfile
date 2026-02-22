# ========== Builder Stage (의존성 설치) ==========
FROM python:3.11-slim AS builder

# uv 설치
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 시스템 의존성 설치 (C 컴파일이 필요한 패키지가 있다면 주석 해제)
#RUN apt-get update && \
#    apt-get install -y --no-install-recommends build-essential && \
#    rm -rf /var/lib/apt/lists/*

# 3. Docker 내부에 가상환경(.venv) 생성
# 컨테이너 안이라도 가상환경을 쓰면 나중에 런타임으로 통째로 복사하기가 쉬워짐
ENV VIRTUAL_ENV=/app/.venv
RUN uv venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# 의존성 복사 및 설치
COPY requirements.txt .
RUN uv pip install --no-cache -r requirements.txt \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple

# ========== Runtime Stage (프로덕션) ==========
FROM python:3.11-slim

WORKDIR /app

# Builder에서 완성된 가상환경(.venv)째로 복사
COPY --from=builder --chown=nobody:nogroup /app/.venv /app/.venv

# 소스 코드 복사
COPY --chown=nobody:nogroup . .

# 비루트 사용자로 실행
USER nobody

# 환경변수
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# 포트 노출
EXPOSE 8000

# 애플리케이션 실행
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]