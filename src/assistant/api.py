"""JSON API routes used by the V2 React frontend."""

import asyncio
import re
import secrets
import threading
from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

import json

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
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
    mode: str = Field(default="auto", max_length=10)


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
            web_qa_service = getattr(request.app.state, "web_qa_service", None)
            if web_qa_service is not None:
                result = await asyncio.to_thread(
                    web_qa_service.answer_question,
                    report,
                    payload.message,
                    history,
                    payload.mode,
                )
                answer = result.answer
                citations = [
                    {"title": source.title, "url": source.url}
                    for source in result.citations
                ]
                web_used = result.used_web
                web_status = result.status
                web_message = result.message
            else:
                answer = await asyncio.to_thread(
                    llm_service.answer_question,
                    report,
                    payload.message,
                    history,
                )
                citations = _extract_citations(answer)
                web_used = False
                web_status = "offline"
                web_message = ""
        except LLMNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except LLMError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        store.save_chat_message(
            session_id,
            "user",
            payload.message,
            metadata={
                "source": "web",
                "web_mode": payload.mode,
                "web_used": web_used,
            },
        )
        store.save_chat_message(
            session_id,
            "assistant",
            answer,
            metadata={
                "source": "web",
                "web_used": web_used,
                "web_status": web_status,
                "web_message": web_message,
            },
        )
        return {
            "answer": answer,
            "session_id": session_id,
            "citations": citations,
            "web_used": web_used,
            "web_status": web_status,
            "web_message": web_message,
        }

    @app.post("/api/chat/stream")
    async def chat_stream(
        request: Request,
    ) -> StreamingResponse:
        active_store = _store(store)
        report = _report(active_store)
        if report is None:
            raise HTTPException(status_code=404, detail="暂无日报快照")
        try:
            raw = await request.body()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            data = json.loads(raw or "{}")
            payload = ChatRequest.model_validate(data)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"请求体必须是有效的 JSON: {exc}",
            ) from exc
        llm_service = getattr(request.app.state, "llm_service", None)
        if llm_service is None:
            raise HTTPException(status_code=503, detail="LLM 服务未配置")
        web_qa_service = getattr(request.app.state, "web_qa_service", None)
        session_id = payload.session_id.strip() or secrets.token_urlsafe(16)
        history = active_store.load_chat_history(
            session_id,
            limit=int(request.app.state.settings.llm_chat_history_limit),
        )

        async def events():
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue[Any] = asyncio.Queue()

            def worker() -> None:
                try:
                    if web_qa_service is None:
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            ("status", {"stage": "starting"}),
                        )
                        answer = llm_service.answer_question(
                            report,
                            payload.message,
                            history,
                        )
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            ("delta", {"text": answer}),
                        )
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            (
                                "result",
                                {
                                    "answer": answer,
                                    "citations": _extract_citations(answer),
                                    "web_used": False,
                                    "web_status": "offline",
                                    "web_message": "",
                                    "stages": ["offline"],
                                },
                            ),
                        )
                    else:
                        for event in web_qa_service.answer_question_events(
                            report,
                            payload.message,
                            history,
                            payload.mode,
                        ):
                            loop.call_soon_threadsafe(
                                queue.put_nowait,
                                (event.event, event.data),
                            )
                except LLMNotConfiguredError as exc:
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        ("error", {"message": str(exc)}),
                    )
                except LLMError as exc:
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        ("error", {"message": str(exc)}),
                    )
                except Exception as exc:
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        ("error", {"message": str(exc)}),
                    )
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            threading.Thread(target=worker, daemon=True).start()
            while True:
                item = await queue.get()
                if item is None:
                    break
                event, data = item
                if event == "result":
                    result_data = dict(data)
                    result_data["session_id"] = session_id
                    yield _sse("result", result_data)
                    active_store.save_chat_message(
                        session_id,
                        "user",
                        payload.message,
                        metadata={
                            "source": "web",
                            "web_mode": payload.mode,
                            "web_used": bool(result_data.get("web_used")),
                        },
                    )
                    active_store.save_chat_message(
                        session_id,
                        "assistant",
                        result_data["answer"],
                        metadata={
                            "source": "web",
                            "web_used": bool(result_data.get("web_used")),
                            "web_status": result_data.get("web_status", ""),
                            "web_message": result_data.get("web_message", ""),
                        },
                    )
                    continue
                yield _sse(event, data)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

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
            "web_search_enabled": settings.web_search_enabled,
            "web_search_model": settings.web_search_model or settings.llm_model,
            "web_daily_limit": settings.web_daily_limit,
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


def _sse(event: str, data: Any) -> str:
    return (
        f"event: {event}\n"
        f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


def _store(store: SnapshotStore | None) -> SnapshotStore:
    if store is None:
        raise HTTPException(status_code=503, detail="存储未配置")
    return store


def _report(store: SnapshotStore | None) -> Any:
    if store is None:
        return None
    return store.load_latest()
