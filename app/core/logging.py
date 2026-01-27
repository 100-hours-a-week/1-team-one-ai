# app/core/logging.py
"""
- def setup_logging(level: int = logging.INFO)
로깅 전략
- 로그 레벨: INFO
- 로그 포맷: [%(asctime)s] %(levelname)s in %(module)s: %(message)s
- 로그 파일: logs/app.log
- 로그 백업: 5개
- 로그 최대 크기: 10MB
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 프로젝트 루트 기준 로그 디렉토리
BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOG_DIR = BASE_DIR / "logs"

# 로그 포맷
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """애플리케이션 로깅을 설정한다.

    Args:
    - level: 로그 레벨 (기본값: logging.INFO)
    """
    LOG_DIR.mkdir(exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 이미 핸들러가 등록된 경우 중복 방지
    if root_logger.handlers:
        return

    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT))

    # 파일 핸들러 (10MB, 최대 5개 백업)
    file_handler = RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
