from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from assistant.config import Settings
from assistant.models import ContentBlock, ContentItem, Report
from assistant.push import PushPlusPushAdapter
from assistant.storage import SnapshotStore


@pytest.fixture
def settings() -> Settings:
    return Settings(
        location="上海",
        timezone="Asia/Shanghai",
        push_channels=["pushplus"],
        pushplus_token="fixture-token",
        push_mock=False,
    )


@pytest.fixture
def report() -> Report:
    return Report(
        title="上海日报 · 2026-08-29",
        generated_at=datetime(
            2026,
            8,
            29,
            8,
            30,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ),
        location="上海",
        timezone="Asia/Shanghai",
        blocks=[
            ContentBlock(
                kind="news",
                title="时事新闻",
                status="ok",
                items=[
                    ContentItem(
                        title="测试新闻",
                        url="https://example.com/1",
                        source="人民网",
                    )
                ],
            )
        ],
    )


@pytest.fixture
def snapshot_store(tmp_path: Path) -> SnapshotStore:
    return SnapshotStore(tmp_path / "fixture.db")


@pytest.fixture
def pushplus_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": 200, "msg": "请求成功", "data": "fixture"},
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def pushplus_adapter(
    settings: Settings,
    pushplus_client: httpx.Client,
) -> PushPlusPushAdapter:
    return PushPlusPushAdapter(settings=settings, client=pushplus_client)
