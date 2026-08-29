from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from assistant.app import create_app
from assistant.config import Settings
from assistant.models import ContentBlock, ContentItem, Report
from assistant.storage import SnapshotStore


def _settings(require_auth: bool) -> Settings:
    return Settings(
        location="上海",
        timezone="Asia/Shanghai",
        data_source_whitelist=["weather", "news", "github", "ai"],
        source_whitelist=["people", "openai"],
        push_channels=["wechat_work"],
        auth_token="secret" if require_auth else "",
        web_require_auth=require_auth,
    )


def _item(title: str, url: str, source: str) -> ContentItem:
    return ContentItem(
        title=title,
        url=url,
        source=source,
        published_at=datetime(2026, 8, 28, 1, 0, tzinfo=timezone.utc),
    )


def _report() -> Report:
    return Report(
        title="上海日报 · 2026-08-28",
        generated_at=datetime(
            2026, 8, 28, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")
        ),
        location="上海",
        timezone="Asia/Shanghai",
        blocks=[
            ContentBlock(
                kind="weather",
                title="上海天气",
                status="ok",
                details={"current": {"temperature": 25.0}},
            ),
            ContentBlock(
                kind="news",
                title="时事新闻",
                items=[_item("新闻一", "https://example.com/news", "人民网")],
            ),
            ContentBlock(
                kind="github",
                title="GitHub 热门",
                items=[_item("openai/evals", "https://github.com/openai/evals", "GitHub Trending")],
            ),
            ContentBlock(
                kind="ai",
                title="AI 领域要事",
                items=[_item("AI 动态", "https://example.com/ai", "OpenAI")],
            ),
        ],
    )


def test_web_requires_token_when_public_auth_is_enabled(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "web.db")
    store.save(_report())
    app = create_app(_settings(require_auth=True), store=store)
    client = TestClient(app)

    assert client.get("/").status_code == 401
    assert client.get("/?token=secret").status_code == 200
    assert (
        client.get("/weather", headers={"Authorization": "Bearer secret"}).status_code
        == 200
    )


def test_web_pages_use_same_saved_snapshot(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "web.db")
    store.save(_report())
    app = create_app(_settings(require_auth=False), store=store)
    client = TestClient(app)

    for path in ["/", "/weather", "/news", "/github", "/ai"]:
        response = client.get(path)
        assert response.status_code == 200
        assert "上海日报 · 2026-08-28" in response.text