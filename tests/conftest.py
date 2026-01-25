# FastAPI TestClient fixture

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s",
)


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
