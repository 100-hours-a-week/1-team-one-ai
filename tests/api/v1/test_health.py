# /api/v1/health 스모크 테스트

from datetime import datetime

from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """헬스체크 엔드포인트 테스트"""

    def test_health_returns_healthy(self, client: TestClient):
        """GET /api/v1/health 요청 시 healthy 상태 반환"""
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_health_response_structure(self, client: TestClient):
        """응답이 HealthResponse 스키마와 일치하는지 확인"""
        response = client.get("/api/v1/health")
        data = response.json()

        assert "status" in data
        assert "version" in data
        assert "timestamp" in data
        assert "services" in data

    def test_health_version_format(self, client: TestClient):
        """version 필드가 올바른 형식인지 확인"""
        response = client.get("/api/v1/health")
        data = response.json()

        assert data["version"].startswith("v")

    def test_health_timestamp_is_valid_iso_format(self, client: TestClient):
        """timestamp가 ISO 8601 형식인지 확인"""
        response = client.get("/api/v1/health")
        data = response.json()

        # ISO 형식 파싱 가능 여부 확인
        datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))

    def test_health_services_contains_api(self, client: TestClient):
        """services에 api 상태가 포함되어 있는지 확인"""
        response = client.get("/api/v1/health")
        data = response.json()

        assert "api" in data["services"]
        assert data["services"]["api"] == "healthy"

    def test_health_response_content_type(self, client: TestClient):
        """응답의 Content-Type이 JSON인지 확인"""
        response = client.get("/api/v1/health")

        assert response.headers["content-type"] == "application/json"
