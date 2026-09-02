"""JSON API routes used by the V2 React frontend."""

import asyncio
import re
import secrets
from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from assistant.llm import LLMError, LLMNotConfiguredError
from assistant.models import (
    favorite_to_dict,
    github_repo_to_dict,
    news_term_to_dict,
    report_to_dict,
    weather_alert_event_to_dict,
    weather_alert_to_dict,
)
from assistant.storage import SnapshotStore

_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")




class FavoriteRequest(BaseModel):
    item_id: str = Field(min_length=1, max_length=100)
    report_date: str = Field(default="", max_length=10)
    block_kind: str = Field(default="", max_length=20)
    title: str = Field(default="", max_length=500)
    url: str = Field(default="", max_length=1000)
    source: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=2000)
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="", max_length=100)


class ChatHistoryItem(BaseModel):
    role: str
    content: str


def register_api_routes(
    app: FastAPI,
    store: SnapshotStore | None,
) -> None:
    """Register report and chat endpoints on the FastAPI app."""

    @app.get("/api/reports/latest")
    def latest_report(request: Request) -> dict[str, Any]:
        report = _report(store)
        if report is None:
            return {"report": None}
        return {"report": report_to_dict(report)}

    @app.get("/api/reports/{report_date}")
    def report_by_date(
        request: Request,
        report_date: date,
    ) -> dict[str, Any]:
        report = _report(store)
        if report is None or report.generated_at.date() != report_date:
            raise HTTPException(status_code=404, detail="未找到指定日报")
        return {"report": report_to_dict(report)}

    @app.get("/api/chat/history")
    def chat_history(
        request: Request,
        session_id: str = Query(min_length=1, max_length=100),
        limit: int = Query(default=50, ge=1, le=100),
    ) -> dict[str, Any]:
        _store(store)
        history = store.load_chat_history(session_id, limit=limit)
        return {"session_id": session_id, "history": history}

    @app.post("/api/chat")
    async def chat(
        request: Request,
        payload: ChatRequest,
    ) -> dict[str, Any]:
        active_store = _store(store)
        report = _report(active_store)
        if report is None:
            raise HTTPException(status_code=404, detail="暂无日报快照")
        llm_service = getattr(request.app.state, "llm_service", None)
        if llm_service is None:
            raise HTTPException(status_code=503, detail="LLM 服务未配置")

        session_id = payload.session_id.strip() or secrets.token_urlsafe(16)
        history = active_store.load_chat_history(
            session_id,
            limit=int(request.app.state.settings.llm_chat_history_limit),
        )
        try:
            answer = await asyncio.to_thread(
                llm_service.answer_question,
                report,
                payload.message,
                history,
            )
        except LLMNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except LLMError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        store.save_chat_message(
            session_id,
            "user",
            payload.message,
            metadata={"source": "web"},
        )
        store.save_chat_message(
            session_id,
            "assistant",
            answer,
            metadata={"source": "web"},
        )
        citations = _extract_citations(answer)
        return {
            "answer": answer,
            "session_id": session_id,
            "citations": citations,
        }

    @app.get("/api/favorites")
    def favorites(
        request: Request,
        block_kind: str | None = Query(default=None, max_length=20),
        limit: int = Query(default=500, ge=1, le=1000),
    ) -> dict[str, Any]:
        active_store = _store(store)
        items = active_store.list_favorites(block_kind=block_kind, limit=limit)
        return {"favorites": [favorite_to_dict(item) for item in items]}

    @app.post("/api/favorites")
    def create_favorite(payload: FavoriteRequest) -> dict[str, Any]:
        active_store = _store(store)
        if payload.block_kind not in ("news", "ai", "github"):
            raise HTTPException(status_code=400, detail="收藏类型仅支持新闻、AI 要事和 GitHub 项目")
        if not payload.item_id.strip():
            raise HTTPException(status_code=400, detail="item_id 不能为空")
        active_store.save_favorite(
            item_id=payload.item_id.strip(),
            report_date=payload.report_date.strip(),
            block_kind=payload.block_kind.strip(),
            title=payload.title.strip(),
            url=payload.url.strip(),
            source=payload.source.strip(),
            note=payload.note.strip(),
        )
        saved = active_store.load_favorite(payload.item_id.strip())
        return {"favorite": favorite_to_dict(saved) if saved else None}

    @app.delete("/api/favorites/{item_id}")
    def delete_favorite(item_id: str) -> dict[str, Any]:
        active_store = _store(store)
        active_store.remove_favorite(item_id)
        return {"deleted": True, "item_id": item_id}

    @app.get("/api/trends")
    def trends(
        request: Request,
        days: int = Query(default=7, ge=1, le=90),
    ) -> dict[str, Any]:
        active_store = _store(store)
        end_date = active_store.latest_report_date()
        if not end_date:
            return {"days": days, "dates": [], "news": [], "github": [], "message": "暂无日报快照"}
        end = date.fromisoformat(end_date)
        start = end - timedelta(days=days - 1)
        active_store.recompute_trends(
            start.isoformat(),
            end.isoformat(),
            min_count=request.app.state.settings.news_trend_min_count,
        )
        dates = [
            (start + timedelta(days=offset)).isoformat()
            for offset in range(days)
        ]
        news = [
            news_term_to_dict(term)
            for term in active_store.load_news_trends(start.isoformat(), end.isoformat())
        ]
        github = [
            github_repo_to_dict(repo)
            for repo in active_store.load_github_trends(start.isoformat(), end.isoformat())
        ]
        return {"days": days, "dates": dates, "news": news, "github": github}


    @app.get("/api/run-status")
    def latest_run_status(request: Request) -> dict[str, Any]:
        status = _store(store).load_latest_run_status()
        return {"run_status": asdict(status) if status else None}

    @app.get("/api/status")
    def status(request: Request) -> dict[str, Any]:
        settings = request.app.state.settings
        llm_service = getattr(request.app.state, "llm_service", None)
        return {
            "llm_configured": bool(
                llm_service is not None and llm_service.configured
            ),
            "llm_summary_enabled": settings.llm_summary_enabled,
            "llm_model": settings.llm_model,
        }


    @app.get("/api/weather-alerts")
    def weather_alerts(
        request: Request,
        status: str | None = Query(default=None, max_length=20),
        location: str | None = Query(default=None, max_length=100),
        alert_type: str | None = Query(default=None, max_length=50),
        limit: int = Query(default=200, ge=1, le=1000),
        event_limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict[str, Any]:
        active_store = _store(store)
        alerts = active_store.list_weather_alerts(
            location=location,
            alert_type=alert_type,
            status=status,
            limit=limit,
        )
        events = active_store.list_weather_alert_events(
            location=location,
            alert_type=alert_type,
            limit=event_limit,
        )
        run = active_store.load_latest_weather_alert_run()
        return {
            "alerts": [weather_alert_to_dict(alert) for alert in alerts],
            "events": [
                weather_alert_event_to_dict(event) for event in events
            ],
            "run": {
                "id": run.id,
                "checked_at": run.checked_at.isoformat() if run.checked_at else "",
                "status": run.status,
                "source": run.source,
                "alert_count": run.alert_count,
                "fallback": run.fallback,
                "message": run.message,
                "created_at": run.created_at.isoformat() if run.created_at else "",
            } if run else None,
        }

def _extract_citations(answer: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for title, url in _LINK_RE.findall(answer):
        result.append({"title": title.strip(), "url": url})
    return result


def _store(store: SnapshotStore | None) -> SnapshotStore:
    if store is None:
        raise HTTPException(status_code=503, detail="存储未配置")
    return store


def _report(store: SnapshotStore | None) -> Any:
    if store is None:
        return None
    return store.load_latest()
