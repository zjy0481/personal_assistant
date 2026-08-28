from fastapi.testclient import TestClient

from assistant.app import create_app
from assistant.config import Settings


def test_health_endpoint_returns_ok() -> None:
    app = create_app(Settings(location="上海", timezone="Asia/Shanghai"))
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_shares_configured_location_with_weather_and_web_surfaces() -> None:
    settings = Settings(
        location="北京",
        timezone="Asia/Shanghai",
        data_source_whitelist=["weather"],
        push_channels=["wechat_work"],
    )
    app = create_app(settings)

    assert app.state.settings is settings
    assert app.state.settings.location == "北京"
