from fastapi.testclient import TestClient

from golden_path_api.config import Settings
from golden_path_api.main import create_app


def client() -> TestClient:
    revision = "0123456789abcdef0123456789abcdef01234567"
    settings = Settings("golden-path-api", "test", "CRITICAL", "0.1.0", revision)
    return TestClient(create_app(settings))


def test_root_reports_build_identity() -> None:
    with client() as api:
        response = api.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "name": "golden-path-api",
        "environment": "test",
        "version": "0.1.0",
        "revision": "0123456789abcdef0123456789abcdef01234567",
    }


def test_health_endpoints() -> None:
    with client() as api:
        assert api.get("/health/live").json() == {"status": "alive"}
        assert api.get("/health/ready").json() == {"status": "ready"}


def test_metrics_are_internal_format() -> None:
    with client() as api:
        response = api.get("/metrics")
    assert response.status_code == 200
    assert "golden_path_http_requests_total" in response.text
    assert response.headers["content-type"].startswith("text/plain")


def test_request_id_is_returned() -> None:
    with client() as api:
        response = api.get("/", headers={"x-request-id": "test-request"})
    assert response.headers["x-request-id"] == "test-request"
