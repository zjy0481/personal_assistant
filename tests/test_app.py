from fastapi.testclient import TestClient

from assistant.app import create_app
from assistant.config import Settings


def test_health_endpoint_returns_ok() -> None:
    app = create_app(Settings(location="上海", timezone="Asia/Shanghai"))
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
