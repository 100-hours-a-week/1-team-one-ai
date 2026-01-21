# FastAPI TestClient fixture

import logging

import pytest
from fastapi.testclient import TestClient

from app.main import app

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s",
)


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient fixture"""
    return TestClient(app)
