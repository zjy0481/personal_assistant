from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from assistant.app import create_app
from assistant.config import Settings
from assistant.llm import LLMClient, LLMService
from assistant.models import ContentBlock, ContentItem, Report
from assistant.storage import RunStatus, SnapshotStore


class _CitationClient(LLMClient):
    def chat(self, messages: list[dict[str, str]]) -> str:
        return "这条新闻值得关注。[测试新闻](https://example.com/1)"


def _report() -> Report:
    return Report(
        title="上海日报 · 2026-08-29",
        generated_at=datetime(2026, 8, 29, 8, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
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
                        source="人民网",
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
    )


def test_latest_report_api_returns_item_id_and_llm_summary(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(tmp_path / "api.db")
    store.save(_report())
    app = create_app(
        _settings(),
        store=store,
        llm_service=LLMService(_settings(), client=_CitationClient()),
    )
    client = TestClient(app)

    response = client.get("/api/reports/latest")

    assert response.status_code == 200
    payload = response.json()["report"]
    item = payload["blocks"][0]["items"][0]
    assert item["item_id"]
    assert item["llm_summary"] == "测试摘要"
    assert item["summary_status"] == "ok"


def test_chat_api_returns_answer_citations_and_persists_history(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(tmp_path / "api.db")
    store.save(_report())
    app = create_app(
        _settings(),
        store=store,
        llm_service=LLMService(_settings(), client=_CitationClient()),
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={"message": "今天有什么值得关注？", "session_id": "session-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == "session-1"
    assert payload["citations"] == [
        {"title": "测试新闻", "url": "https://example.com/1"}
    ]
    history = client.get(
        "/api/chat/history?session_id=session-1"
    ).json()["history"]
    assert [item["role"] for item in history] == ["user", "assistant"]


def test_chat_api_returns_503_without_llm_key(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "api.db")
    store.save(_report())
    settings = Settings(location="上海", timezone="Asia/Shanghai", llm_api_key="")
    app = create_app(settings, store=store, llm_service=LLMService(settings))
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={"message": "今天有什么值得关注？", "session_id": "session-1"},
    )

    assert response.status_code == 503

def test_run_status_api_returns_latest_status(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "status.db")
    store.save(_report())
    store.save_run_status(
        RunStatus(report_date="2026-08-29", status="ok", channel="pushplus", message="成功")
    )
    app = create_app(
        _settings(),
        store=store,
        llm_service=LLMService(_settings(), client=_CitationClient()),
    )

    response = TestClient(app).get("/api/run-status")

    assert response.status_code == 200
    assert response.json()["run_status"]["status"] == "ok"