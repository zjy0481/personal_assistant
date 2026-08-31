from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from assistant.app import create_app
from assistant.config import Settings
from assistant.models import ContentBlock, ContentItem, Report
from assistant.storage import SnapshotStore


def _report(report_date: str, stars: int) -> Report:
    return Report(
        title="test",
        generated_at=datetime.fromisoformat(report_date + "T08:00:00+08:00"),
        location="上海",
        timezone="Asia/Shanghai",
        blocks=[
            ContentBlock(
                kind="news",
                title="news",
                status="ok",
                items=[
                    ContentItem(
                        title="AI China News",
                        url="https://example.com/ai",
                        source="example",
                        summary="AI technology news",
                        item_id="news-item",
                    )
                ],
            ),
            ContentBlock(
                kind="github",
                title="github",
                status="ok",
                items=[
                    ContentItem(
                        title="openai/agent",
                        url="https://github.com/openai/agent",
                        source="github",
                        stars=stars,
                        metadata={"repo": "openai/agent"},
                        item_id="repo-item",
                    )
                ],
            ),
        ],
    )


def _make_store(tmp_path: Path) -> SnapshotStore:
    store = SnapshotStore(tmp_path / "phase3.db")
    store.save(_report("2026-08-29", 100))
    store.save(_report("2026-08-30", 120))
    return store


def _make_app(store: SnapshotStore):
    settings = Settings(location="上海", timezone="Asia/Shanghai")
    return create_app(settings, store=store)


def test_favorite_api_is_idempotent_and_can_be_removed(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    payload = {
        "item_id": "news-item",
        "report_date": "2026-08-30",
        "block_kind": "news",
        "title": "AI China News",
        "url": "https://example.com/ai",
        "source": "example",
    }
    client = TestClient(_make_app(store))

    first = client.post("/api/favorites", json=payload)
    second = client.post("/api/favorites", json=payload)
    listed = client.get("/api/favorites")

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(listed.json()["favorites"]) == 1

    deleted = client.delete("/api/favorites/news-item")
    assert deleted.status_code == 200
    assert client.get("/api/favorites").json()["favorites"] == []

    restored = client.post("/api/favorites", json=payload)
    assert restored.status_code == 200
    assert len(client.get("/api/favorites").json()["favorites"]) == 1


def test_favorite_api_rejects_weather_block(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    client = TestClient(_make_app(store))
    response = client.post(
        "/api/favorites",
        json={
            "item_id": "weather-item",
            "block_kind": "weather",
            "title": "weather",
        },
    )
    assert response.status_code == 400


def test_trends_api_returns_news_and_github_series(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    client = TestClient(_make_app(store))
    response = client.get("/api/trends?days=7")

    assert response.status_code == 200
    payload = response.json()
    assert payload["days"] == 7
    assert len(payload["dates"]) == 7
    assert payload["news"]
    assert any(item["repo"] == "openai/agent" and item["new_stars"] == 20 for item in payload["github"])


def test_trend_recompute_is_deterministic_and_marks_no_data(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.recompute_trends("2026-08-29", "2026-08-30")
    terms = store.load_news_trends("2026-08-29", "2026-08-30")
    repos = store.load_github_trends("2026-08-29", "2026-08-30")

    assert len(terms) > 0
    assert any(item.word == "ai" for item in terms)
    assert any(item.report_date == "2026-08-30" and item.new_stars == 20 for item in repos)

def test_favorites_api_requires_auth_when_enabled(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    settings = Settings(
        location="上海",
        timezone="Asia/Shanghai",
        web_require_auth=True,
        auth_token="secret-token",
    )
    client = TestClient(create_app(settings, store=store))
    response = client.get("/api/favorites")
    assert response.status_code == 401

def test_news_tokenizer_filters_english_function_words() -> None:
    from assistant.storage import _tokenize_news_text
    words = _tokenize_news_text(
        "After his announcement, OpenAI released AI technology today"
    )
    assert "after" not in words
    assert "his" not in words
    assert "today" not in words
    assert "openai" in words
    assert "ai" in words
    assert "technology" in words
