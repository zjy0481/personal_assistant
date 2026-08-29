from fastapi import FastAPI

from assistant.main import app


def test_main_exposes_a_configured_fastapi_app() -> None:
    assert isinstance(app, FastAPI)
    assert app.state.settings.location == "上海"
