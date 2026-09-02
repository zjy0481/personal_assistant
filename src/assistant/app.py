"""FastAPI application factory."""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from assistant.api import register_api_routes
from assistant.config import Settings
from assistant.llm import LLMService, create_llm_service
from assistant.models import report_to_dict
from assistant.storage import RunStatus, SnapshotStore

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def create_app(
    settings: Settings,
    store: SnapshotStore | None = None,
    llm_service: LLMService | None = None,
    frontend_dir: Path | None = None,
) -> FastAPI:
    """Create the web application sharing one report snapshot store."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if store is not None:
            store.delete_expired_chat_messages(
                settings.llm_chat_retention_days
            )
            store.delete_expired_weather_alerts(
                settings.weather_alert_retention_days
            )
            store.delete_expired_wecom_ai_messages(
                settings.wecom_ai_retention_days
            )
            store.delete_expired_trend_snapshots(
                settings.trend_retention_days,
            )
        yield

    app = FastAPI(title="Personal Assistant", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.llm_service = llm_service or create_llm_service(settings)
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
            {
                "report": _latest_report(app),
                "run_status": _latest_run_status(app),
            },
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

    if frontend_dir is not None:
        _serve_frontend(app, frontend_dir)

    register_api_routes(app, store)
    return app


def _serve_frontend(app: FastAPI, frontend_dir: Path) -> None:
    """Serve the built Vite React app under /app with SPA fallback."""
    root = Path(frontend_dir).resolve()

    @app.get("/app", response_model=None)
    @app.get("/app/{path:path}", response_model=None)
    def frontend(path: str = "index.html") -> FileResponse | HTMLResponse:
        if not root.is_dir():
            return HTMLResponse(
                "<h1>前端尚未构建</h1><p>请运行 cd web && npm run build</p>",
                status_code=404,
            )
        target = (root / path).resolve()
        if target.is_file() and root in target.parents:
            return FileResponse(target)
        index = root / "index.html"
        if index.exists():
            return FileResponse(index)
        return HTMLResponse("<h1>前端尚未构建</h1>", status_code=404)


def _latest_report(app: FastAPI) -> dict | None:
    if app.state.store is None:
        return None
    report = app.state.store.load_latest()
    return report_to_dict(report) if report is not None else None


def _latest_run_status(app: FastAPI) -> RunStatus | None:
    if app.state.store is None:
        return None
    return app.state.store.load_latest_run_status()
