# FastAPI TestClient fixture

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)

logger = logging.getLogger("pytest")

# 현재 실행 중인 테스트 파일 추적
_current_test_file: str | None = None


def pytest_runtest_setup(item: pytest.Item) -> None:
    """각 테스트 파일 및 함수 시작 시 로깅"""
    global _current_test_file
    test_file = str(item.fspath)

    # 파일 단위 로깅
    if test_file != _current_test_file:
        _current_test_file = test_file
        relative_path = Path(test_file).relative_to(Path(__file__).parent.parent)
        logger.info(f"{'=' * 60}")
        logger.info(f"테스트 파일 시작: {relative_path}")
        logger.info(f"{'=' * 60}")

    # 함수 단위 로깅
    logger.info(f"  ▶ 테스트 함수 시작: {item.name}")


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """각 테스트 함수 완료 시 결과 로깅"""
    if report.when == "call":
        status_icon = {
            "passed": "✓",
            "failed": "✗",
            "skipped": "⊘",
        }.get(report.outcome, "?")
        logger.info(f"  {status_icon} 테스트 함수 완료: {report.nodeid.split('::')[-1]} [{report.outcome}]")


@pytest.fixture(scope="session")
def client() -> TestClient:
    """FastAPI TestClient fixture"""
    return TestClient(app)


@pytest.fixture(scope="session")
def exercise_data():
    path = Path(__file__).parent / "fixtures" / "exercises.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def user_data():
    path = Path(__file__).parent / "fixtures" / "users.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def llm_inference_data():
    path = Path(__file__).parent / "fixtures" / "llm_inference.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)
