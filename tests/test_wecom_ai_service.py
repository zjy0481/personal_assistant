"""Tests for the Enterprise WeChat smart robot long-connection service."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from assistant.config import Settings
from assistant.llm import LLMError
from assistant.models import ContentBlock, ContentItem, Report
from assistant.storage import SnapshotStore
from assistant.wecom_ai_service import (
    WeComAIBot,
    WeComAIConfigError,
    has_bot_mention,
    parse_message_payload,
    strip_bot_mention,
)


class FakeLLM:
    def __init__(self, answer: str = "这是回答", error: Exception | None = None):
        self.answer = answer
        self.error = error
        self.calls: list[tuple[Report, str, list[dict[str, str]] | None]] = []

    def answer_question(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        self.calls.append((report, question, history))
        if self.error:
            raise self.error
        return self.answer


class FakeWebSocket:
    def __init__(self, frames: list[dict] | None = None):
        self.frames = list(frames or [])
        self.sent: list[dict] = []

    def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    def recv(self, timeout: float | None = None):
        if self.frames:
            return json.dumps(self.frames.pop(0))
        raise TimeoutError()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def make_settings(**overrides) -> Settings:
    values = {
        "location": "上海",
        "timezone": "Asia/Shanghai",
        "wecom_ai_enabled": True,
        "wecom_ai_mode": "long_connection",
        "wecom_ai_bot_id": "bot-id",
        "wecom_ai_bot_secret": "bot-secret",
        "wecom_ai_bot_name": "雪球日报助手",
        "llm_chat_history_limit": 20,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def make_report() -> Report:
    return Report(
        title="上海日报 · 2026-08-30",
        generated_at=datetime(
            2026, 8, 30, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")
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


def make_store(tmp_path) -> tuple[SnapshotStore, Report]:
    store = SnapshotStore(tmp_path / "wecom.db")
    report = make_report()
    store.save(report)
    return store, report


def make_payload(content: str = "@雪球日报助手 今天有什么新闻？") -> dict:
    return {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "req-1"},
        "body": {
            "msgid": "msg-1",
            "aibotid": "bot-id",
            "chatid": "chat-1",
            "chattype": "group",
            "from": {"userid": "user-1"},
            "msgtype": "text",
            "text": {"content": content},
        },
    }


def test_parse_and_strip_mention() -> None:
    payload = make_payload()
    message = parse_message_payload(payload)
    assert message is not None
    assert message.chat_id == "chat-1"
    assert message.from_userid == "user-1"
    assert has_bot_mention(message.content, "雪球日报助手") is True
    assert strip_bot_mention(message.content, "雪球日报助手") == "今天有什么新闻？"


def test_parse_mixed_message_joins_text_items() -> None:
    payload = make_payload()
    payload["body"] = {
        "msgid": "msg-2",
        "chatid": "chat-1",
        "chattype": "group",
        "from": {"userid": "user-1"},
        "msgtype": "mixed",
        "mixed": {
            "msg_item": [
                {"msgtype": "text", "text": {"content": "@雪球日报助手 问题一"}},
                {"msgtype": "text", "text": {"content": "问题二"}},
            ]
        },
    }
    message = parse_message_payload(payload)
    assert message is not None
    assert "问题一" in message.content
    assert "问题二" in message.content


def test_group_at_message_answers_and_persists(tmp_path) -> None:
    store, report = make_store(tmp_path)
    llm = FakeLLM(answer="日报中的新闻是测试新闻。")
    bot = WeComAIBot(
        make_settings(),
        store=store,
        llm_service=llm,
    )
    ws = FakeWebSocket()
    bot._handle_frame(ws, json.dumps(make_payload()))

    assert len(ws.sent) == 1
    reply = ws.sent[0]
    assert reply["cmd"] == "aibot_respond_msg"
    assert reply["headers"]["req_id"] == "req-1"
    assert reply["body"]["msgtype"] == "markdown"
    assert "测试新闻" in reply["body"]["markdown"]["content"]
    assert llm.calls[0][1] == "今天有什么新闻？"
    assert store.load_chat_history("wecom:chat-1:user-1") != []
    assert store.load_wecom_ai_message("msg-1")["status"] == "replied"


def test_duplicate_msgid_is_not_reprocessed(tmp_path) -> None:
    store, _ = make_store(tmp_path)
    llm = FakeLLM()
    bot = WeComAIBot(make_settings(), store=store, llm_service=llm)
    ws = FakeWebSocket()
    bot._handle_frame(ws, json.dumps(make_payload()))
    bot._handle_frame(ws, json.dumps(make_payload()))
    assert len(ws.sent) == 1
    assert len(llm.calls) == 1


def test_unlisted_chat_and_user_are_ignored(tmp_path) -> None:
    store, _ = make_store(tmp_path)
    llm = FakeLLM()
    settings = make_settings(
        wecom_ai_allowed_chat_ids=["chat-allowed"],
        wecom_ai_allowed_user_ids=["user-allowed"],
    )
    bot = WeComAIBot(settings, store=store, llm_service=llm)
    ws = FakeWebSocket()
    bot._handle_frame(ws, json.dumps(make_payload()))
    assert ws.sent == []
    assert llm.calls == []


def test_group_message_without_mention_is_ignored(tmp_path) -> None:
    store, _ = make_store(tmp_path)
    llm = FakeLLM()
    bot = WeComAIBot(make_settings(), store=store, llm_service=llm)
    ws = FakeWebSocket()
    bot._handle_frame(ws, json.dumps(make_payload("今天有什么新闻？")))
    assert ws.sent == []
    assert llm.calls == []


def test_llm_failure_returns_fallback_and_records_failed(tmp_path) -> None:
    store, _ = make_store(tmp_path)
    llm = FakeLLM(error=LLMError("模型异常"))
    bot = WeComAIBot(make_settings(), store=store, llm_service=llm)
    ws = FakeWebSocket()
    bot._handle_frame(ws, json.dumps(make_payload()))
    assert len(ws.sent) == 1
    assert "抱歉" in ws.sent[0]["body"]["markdown"]["content"]
    assert store.load_wecom_ai_message("msg-1")["status"] == "failed"


def test_missing_credentials_raise_config_error() -> None:
    bot = WeComAIBot(
        make_settings(wecom_ai_enabled=False, wecom_ai_bot_secret=""),
        store=SnapshotStore.__new__(SnapshotStore),
        llm_service=FakeLLM(),
    )
    with pytest.raises(WeComAIConfigError):
        bot.validate()


def test_subscribe_accepts_official_response_without_cmd(tmp_path, monkeypatch) -> None:
    store, _ = make_store(tmp_path)
    bot = WeComAIBot(make_settings(), store=store, llm_service=FakeLLM())
    ws = FakeWebSocket(frames=[{"headers": {"req_id": "req-test"}, "errcode": 0}])
    monkeypatch.setattr(
        "assistant.wecom_ai_service._new_req_id",
        lambda: "req-test",
    )
    bot._subscribe(ws)
    assert ws.sent[0]["cmd"] == "aibot_subscribe"
    assert ws.sent[0]["body"]["bot_id"] == "bot-id"


class StopTest(Exception):
    pass


class FakeSessionWebSocket(FakeWebSocket):
    def recv(self, timeout: float | None = None):
        if self.frames:
            return json.dumps(self.frames.pop(0))
        raise StopTest()


def test_run_session_subscribes_and_handles_message(tmp_path, monkeypatch) -> None:
    store, _ = make_store(tmp_path)
    ws = FakeSessionWebSocket(
        frames=[
            {"headers": {"req_id": "req-test"}, "errcode": 0},
            make_payload(),
        ]
    )
    bot = WeComAIBot(
        make_settings(),
        store=store,
        llm_service=FakeLLM(answer="完整链路回答"),
        connect_factory=lambda *args, **kwargs: ws,
    )
    monkeypatch.setattr(
        "assistant.wecom_ai_service._new_req_id",
        lambda: "req-test",
    )
    with pytest.raises(StopTest):
        bot._run_session()
    assert ws.sent[0]["cmd"] == "aibot_subscribe"
    assert ws.sent[1]["cmd"] == "aibot_respond_msg"
    assert ws.sent[1]["headers"]["req_id"] == "req-1"


class FakeReconnectWebSocket(FakeSessionWebSocket):
    def recv(self, timeout: float | None = None):
        if self.frames:
            return json.dumps(self.frames.pop(0))
        raise ConnectionError("模拟断线")


def test_run_reconnects_after_connection_error(tmp_path) -> None:
    store, _ = make_store(tmp_path)
    ws = FakeReconnectWebSocket()
    bot = WeComAIBot(
        make_settings(),
        store=store,
        llm_service=FakeLLM(),
        connect_factory=lambda *args, **kwargs: ws,
    )
    bot._sleep = lambda delay: bot.stop()
    bot.run()
    assert ws.sent[0]["cmd"] == "aibot_subscribe"
