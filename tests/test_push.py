import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from assistant.config import Settings
from assistant.models import ContentBlock, ContentItem, Report
from assistant.push import (
    MockPushAdapter,
    PushResult,
    WeComPushAdapter,
    create_push_adapter,
)


def _settings() -> Settings:
    return Settings(
        location="上海",
        timezone="Asia/Shanghai",
        push_channels=["wechat_work"],
        wecom_corpid="ww-test",
        wecom_agentid="1000002",
        wecom_secret="secret",
        wecom_userid="zhangsan",
        wecom_mock=False,
    )


def _report() -> Report:
    return Report(
        title="上海日报 · 2026-08-28",
        generated_at=datetime(2026, 8, 28, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
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
                    )
                ],
            )
        ],
    )


def test_settings_carries_wecom_configuration() -> None:
    settings = _settings()

    assert settings.wecom_corpid == "ww-test"
    assert settings.wecom_agentid == "1000002"
    assert settings.wecom_secret == "secret"
    assert settings.wecom_userid == "zhangsan"
    assert settings.wecom_mock is False


def test_wecom_adapter_sends_textcard_first() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        url = str(request.url)
        if "gettoken" in url:
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "access_token": "access-token",
                },
            )
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    adapter = WeComPushAdapter(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        settings=Settings(
            wecom_corpid="ww-test",
            wecom_agentid="1000002",
            wecom_secret="secret",
            wecom_userid="zhangsan",
            wecom_mock=False,
        ),
    )

    result = adapter.send_report(_report())

    assert result.success is True
    assert result.mode == "textcard"
    send_request = requests[-1]
    payload = json.loads(send_request.content)
    assert payload["msgtype"] == "textcard"
    assert payload["textcard"]["title"] == "上海日报 · 2026-08-28"


def test_wecom_adapter_falls_back_to_text() -> None:
    send_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal send_count
        if "gettoken" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "access_token": "access-token",
                },
            )
        send_count += 1
        if send_count == 1:
            return httpx.Response(
                200,
                json={"errcode": 40001, "errmsg": "invalid credential"},
            )
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    adapter = WeComPushAdapter(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        settings=_settings(),
    )

    result = adapter.send_report(_report())

    assert result.success is True
    assert result.mode == "text"
    assert send_count == 2


def test_wecom_adapter_reports_failure_and_notifies() -> None:
    notifications: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "gettoken" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "access_token": "access-token",
                },
            )
        return httpx.Response(
            200,
            json={"errcode": 50001, "errmsg": "service unavailable"},
        )

    adapter = WeComPushAdapter(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        settings=_settings(),
        failure_notifier=notifications.append,
    )

    result = adapter.send_report(_report())

    assert result.success is False
    assert result.mode == "failed"
    assert notifications
    assert "发送失败" in notifications[0]


def test_mock_adapter_validates_push_flow() -> None:
    adapter = MockPushAdapter(
        result=PushResult(success=True, mode="mock")
    )

    result = adapter.send_report(_report())

    assert result.success is True
    assert result.mode == "mock"


def test_create_push_adapter_returns_mock_when_configured() -> None:
    settings = _settings()
    settings.wecom_mock = True

    adapter = create_push_adapter(settings)

    assert isinstance(adapter, MockPushAdapter)