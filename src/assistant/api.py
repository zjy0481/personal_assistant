"""JSON API routes used by the V2 React frontend."""

import asyncio
import re
import secrets
from dataclasses import asdict
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from assistant.llm import LLMError, LLMNotConfiguredError
from assistant.models import report_to_dict
from assistant.storage import SnapshotStore

_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")


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