"""Integration tests for the V3 web chat API."""

from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from assistant.app import create_app
from assistant.config import Settings
from assistant.llm import LLMService, MockLLMClient
from assistant.models import ContentBlock, ContentItem, Report
from assistant.storage import SnapshotStore
from assistant.web_qa import WebAnswer, WebStreamEvent
from assistant.web_search import WebSource


def _report() -> Report:
    return Report(
        title="上海日报 · 2026-09-02",
        generated_at=datetime(
            2026,
            9,
            2,
            8,
            0,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ),
        location="上海",
        timezone="Asia/Shanghai",
        blocks=[
            ContentBlock(
                kind="news",
                title="时事新闻",
                items=[
                    ContentItem(
                        title="测试新闻",
                        url="https://example.com/1",
                        source="测试源",
                        llm_summary="测试摘要",
                        summary_status="ok",
                    )
                ],
            )
        ],
    )


def _settings() -> Settings:
    return Settings(
        location="上海",
        timezone="Asia/Shanghai",
        llm_api_key="test-key",
        web_search_enabled=True,
        web_daily_limit=10,
    )


class FakeWebQA:
    def __init__(self):
        self.calls = 0

    def answer_question(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]] | None = None,
        mode: str = "auto",
    ) -> WebAnswer:
        self.calls += 1
        self.last_mode = mode
        return WebAnswer(
            answer="已联网：今天有测试新闻。[测试新闻](https://example.com/news)",
            citations=[WebSource("测试新闻", "https://example.com/news")],
            used_web=True,
            status="ok",
            stages=["searching", "answering"],
        )

    def answer_question_events(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]] | None = None,
        mode: str = "auto",
    ):
        result = self.answer_question(report, question, history, mode)
        yield WebStreamEvent("status", {"stage": "starting"})
        yield WebStreamEvent("status", {"stage": "searching"})
        yield WebStreamEvent("status", {"stage": "answering"})
        yield WebStreamEvent("delta", {"text": result.answer})
        yield WebStreamEvent("result", {
            "answer": result.answer,
            "citations": [
                {"title": source.title, "url": source.url}
                for source in result.citations
            ],
            "web_used": result.used_web,
            "web_status": result.status,
            "web_message": result.message,
            "stages": result.stages,
        })


def _client(tmp_path: Path, web_qa: FakeWebQA) -> TestClient:
    store = SnapshotStore(tmp_path / "web-api.db")
    store.save(_report())
    settings = _settings()
    app = create_app(
        settings,
        store=store,
        llm_service=LLMService(settings, client=MockLLMClient()),
        web_qa_service=web_qa,
    )
    return TestClient(app)


def test_chat_api_returns_web_answer_and_citations(tmp_path: Path) -> None:
    web_qa = FakeWebQA()
    client = _client(tmp_path, web_qa)

    response = client.post(
        "/api/chat",
        json={"message": "今天有什么值得关注？", "session_id": "session-web"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["web_used"] is True
    assert payload["web_status"] == "ok"
    assert payload["citations"] == [
        {"title": "测试新闻", "url": "https://example.com/news"}
    ]
    assert web_qa.calls == 1


def test_chat_stream_endpoint_returns_sse_result(tmp_path: Path) -> None:
    web_qa = FakeWebQA()
    client = _client(tmp_path, web_qa)

    response = client.post(
        "/api/chat/stream",
        json={"message": "今天有什么值得关注？", "session_id": "session-web"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert '"answer":' in body
    assert '"session_id":' in body


def test_chat_stream_accepts_body_without_json_content_type(
    tmp_path: Path,
) -> None:
    web_qa = FakeWebQA()
    client = _client(tmp_path, web_qa)

    response = client.post(
        "/api/chat/stream",
        content=json.dumps(
            {
                "message": "今天有什么值得关注？",
                "session_id": "session-web",
                "mode": "auto",
            }
        ),
        headers={"Content-Type": "text/plain"},
    )

    assert response.status_code == 200
    assert "event: result" in response.text
