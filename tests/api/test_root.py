# / 루트 엔드포인트 테스트

from fastapi.testclient import TestClient


class TestRootEndpoint:
    """루트 엔드포인트 테스트"""

    def test_root_returns_ok(self, client: TestClient):
        """GET / 요청 시 status ok 반환"""
        response = client.get("/")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_root_response_content_type(self, client: TestClient):
        """GET / 응답의 Content-Type이 JSON인지 확인"""
        response = client.get("/")

        assert response.headers["content-type"] == "application/json"
