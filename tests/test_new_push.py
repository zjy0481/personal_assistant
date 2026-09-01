import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from assistant.config import Settings
from assistant.models import ContentBlock, ContentItem, Report
from assistant.push import (
    MockPushAdapter,
    PushChainAdapter,
    PushPlusPushAdapter,
    PushResult,
    WeComGroupWebhookPushAdapter,
    create_push_adapter,
)


def _settings() -> Settings:
    return Settings(
        location="上海",
        timezone="Asia/Shanghai",
        push_channels=["wecom_group", "pushplus"],
        pushplus_token="pushplus-token",
        wecom_group_webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
        push_max_items=3,
        push_mock=False,
    )


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


def test_pushplus_adapter_sends_markdown_and_records_short_code() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"code": 200, "msg": "请求成功", "data": "abc-123"})

    adapter = PushPlusPushAdapter(
        settings=_settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = adapter.send_report(_report())

    assert result.success is True
    assert result.channel == "pushplus"
    assert result.short_code == "abc-123"
    payload = json.loads(requests[-1].content)
    assert payload["token"] == "pushplus-token"
    assert payload["template"] == "markdown"
    assert "上海日报" in payload["content"]


def test_pushplus_adapter_fails_when_api_returns_error_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 905, "msg": "未实名认证"})

    adapter = PushPlusPushAdapter(
        settings=_settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = adapter.send_report(_report())

    assert result.success is False
    assert result.channel == "pushplus"
    assert result.errcode == 905


def test_wecom_group_adapter_sends_markdown() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    adapter = WeComGroupWebhookPushAdapter(
        settings=_settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = adapter.send_report(_report())

    assert result.success is True
    assert result.channel == "wecom_group"
    payload = json.loads(requests[-1].content)
    assert payload["msgtype"] == "markdown"
    assert "测试新闻" in payload["markdown"]["content"]


def test_wecom_group_adapter_fails_on_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errcode": 40001, "errmsg": "invalid key"})

    adapter = WeComGroupWebhookPushAdapter(
        settings=_settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = adapter.send_report(_report())

    assert result.success is False
    assert result.channel == "wecom_group"
    assert result.errcode == 40001


class _StubAdapter:
    def __init__(self, success: bool, channel: str, message: str = "") -> None:
        self.success = success
        self._channel = channel
        self._message = message

    def send_report(self, report: Report) -> PushResult:
        return PushResult(
            success=self.success,
            mode=self._channel,
            channel=self._channel,
            message=self._message,
        )


def test_push_chain_uses_secondary_when_primary_fails() -> None:
    chain = PushChainAdapter(
        [
            _StubAdapter(False, "pushplus"),
            _StubAdapter(True, "wecom_group"),
        ]
    )

    result = chain.send_report(_report())

    assert result.success is True
    assert result.channel == "wecom_group"
    assert result.fallback is True


def test_push_chain_notifies_once_when_all_channels_fail() -> None:
    notifications: list[str] = []
    chain = PushChainAdapter(
        [
            _StubAdapter(False, "pushplus", "主渠道失败"),
            _StubAdapter(False, "wecom_group", "备用渠道失败"),
        ],
        failure_notifier=notifications.append,
    )

    result = chain.send_report(_report())

    assert result.success is False
    assert len(notifications) == 1
    assert "主渠道失败" in notifications[0]
    assert "备用渠道失败" in notifications[0]


def test_create_push_adapter_uses_ordered_webhook_then_pushplus() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "qyapi.weixin.qq.com" in str(request.url):
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
        return httpx.Response(200, json={"code": 200, "data": "abc"})

    settings = _settings()
    adapter = create_push_adapter(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = adapter.send_report(_report())

    assert result.success is True
    assert result.channel == "wecom_group"
    assert len(calls) == 1
    assert "qyapi.weixin.qq.com" in calls[0]


def test_create_push_adapter_falls_back_to_pushplus_when_webhook_rejects() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "qyapi.weixin.qq.com" in str(request.url):
            return httpx.Response(200, json={"errcode": 40001, "errmsg": "invalid key"})
        return httpx.Response(200, json={"code": 200, "data": "abc"})

    adapter = create_push_adapter(
        _settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = adapter.send_report(_report())

    assert result.success is True
    assert result.channel == "pushplus"
    assert result.fallback is True
    assert len(calls) == 2
    assert "pushplus.plus" in calls[1]

def test_create_push_adapter_returns_mock_when_push_mock() -> None:
    settings = _settings()
    settings.push_mock = True

    adapter = create_push_adapter(settings)

    assert isinstance(adapter, MockPushAdapter)
