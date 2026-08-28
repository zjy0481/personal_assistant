"""FastAPI application factory."""

from fastapi import FastAPI

from assistant.config import Settings


def create_app(settings: Settings) -> FastAPI:
    """Create the web application."""

    app = FastAPI(title="Personal Assistant")
    app.state.settings = settings

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
