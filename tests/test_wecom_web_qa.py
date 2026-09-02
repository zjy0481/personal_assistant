"""Tests for V3 enterprise WeChat web Q&A commands and formatting."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from assistant.config import Settings
from assistant.models import ContentBlock, ContentItem, Report
from assistant.storage import SnapshotStore
from assistant.wecom_ai_service import WeComAIBot
from assistant.web_qa import WebAnswer
from assistant.web_search import WebSource


class FakeWebQA:
    def __init__(self, answer: str = "已联网回答 [来源](https://example.com/news)"):
        self.answer = answer
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
        self.last_question = question
        return WebAnswer(
            answer=self.answer,
            citations=[WebSource("来源", "https://example.com/news")],
            used_web=True,
            status="ok",
            stages=["searching", "answering"],
        )


class FakeLLM:
    def answer_question(self, report, question, history=None):
        return "离线回答"


class FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


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
        "web_search_enabled": True,
        "web_daily_limit": 10,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def make_report() -> Report:
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
                items=[ContentItem("测试新闻", "https://example.com/1", "测试源")],
            )
        ],
    )


def make_store(tmp_path) -> SnapshotStore:
    store = SnapshotStore(tmp_path / "wecom-web.db")
    store.save(make_report())
    return store


def make_payload(content: str) -> dict:
    return {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "req-web"},
        "body": {
            "msgid": "msg-web",
            "aibotid": "bot-id",
            "chatid": "chat-web",
            "chattype": "group",
            "from": {"userid": "user-web"},
            "msgtype": "text",
            "text": {"content": content},
        },
    }


def test_force_web_command_marks_reply_and_uses_web_qa(tmp_path) -> None:
    store = make_store(tmp_path)
    web_qa = FakeWebQA()
    bot = WeComAIBot(
        make_settings(),
        store=store,
        llm_service=FakeLLM(),
        web_qa_service=web_qa,
    )
    ws = FakeWebSocket()

    bot._handle_frame(
        ws,
        json.dumps(
            make_payload("@雪球日报助手 联网：今天有什么新闻？")
        ),
    )

    assert web_qa.calls == 1
    assert web_qa.last_mode == "force"
    reply = ws.sent[0]["body"]["markdown"]["content"]
    assert "已联网检索" in reply
    assert "https://example.com/news" in reply


def test_offline_command_never_calls_web_qa(tmp_path) -> None:
    store = make_store(tmp_path)
    web_qa = FakeWebQA()
    llm = FakeLLM()
    bot = WeComAIBot(
        make_settings(),
        store=store,
        llm_service=llm,
        web_qa_service=web_qa,
    )
    ws = FakeWebSocket()

    bot._handle_frame(
        ws,
        json.dumps(
            make_payload("@雪球日报助手 不联网：今天有什么新闻？")
        ),
    )

    assert web_qa.calls == 0
    assert ws.sent[0]["body"]["markdown"]["content"] == "离线回答"
