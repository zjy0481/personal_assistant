"""FastAPI application factory."""

import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from assistant.config import Settings
from assistant.models import report_to_dict
from assistant.storage import SnapshotStore

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def create_app(
    settings: Settings,
    store: SnapshotStore | None = None,
) -> FastAPI:
    """Create the web application sharing one report snapshot store."""

    app = FastAPI(title="Personal Assistant")
    app.state.settings = settings
    app.state.store = store
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

    @app.middleware("http")
    async def require_web_token(request: Request, call_next):
        if settings.web_require_auth and request.url.path != "/health":
            token = request.query_params.get("token")
            authorization = request.headers.get("authorization", "")
            if authorization.lower().startswith("bearer "):
                token = authorization[7:].strip()
            if not token or not secrets.compare_digest(
                token,
                settings.auth_token,
            ):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "未授权：请提供网页访问 token"},
                )
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def home(request: Request):
        return templates.TemplateResponse(
            request,
            "home.html",
            {"report": _latest_report(app)},
        )

    @app.get("/weather")
    def weather_page(request: Request):
        return templates.TemplateResponse(
            request,
            "weather.html",
            {"report": _latest_report(app)},
        )

    @app.get("/news")
    def news_page(request: Request):
        return templates.TemplateResponse(
            request,
            "news.html",
            {"report": _latest_report(app)},
        )

    @app.get("/github")
    def github_page(request: Request):
        return templates.TemplateResponse(
            request,
            "github.html",
            {"report": _latest_report(app)},
        )

    @app.get("/ai")
    def ai_page(request: Request):
        return templates.TemplateResponse(
            request,
            "ai.html",
            {"report": _latest_report(app)},
        )

    return app


def _latest_report(app: FastAPI) -> dict | None:
    if app.state.store is None:
        return None
    report = app.state.store.load_latest()
    return report_to_dict(report) if report is not None else None