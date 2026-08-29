from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from assistant.config import Settings
from assistant.llm import (
    LLMRateLimitError,
    LLMRateLimiter,
    LLMService,
    MockLLMClient,
    LLMClient,
)
from assistant.models import ContentBlock, ContentItem, Report


class CitationClient(LLMClient):
    def chat(self, messages: list[dict[str, str]]) -> str:
        return "这条新闻值得关注。[测试新闻](https://example.com/1)"


def _settings() -> Settings:
    return Settings(
        location="上海",
        timezone="Asia/Shanghai",
        llm_api_key="test-key",
        llm_model="deepseek-v4-flash",
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


def test_summarize_report_sets_chinese_summary_for_items() -> None:
    service = LLMService(_settings(), client=MockLLMClient())
    report = _report()

    service.summarize_report(report)

    item = report.blocks[0].items[0]
    assert item.summary_status == "ok"
    assert item.llm_summary == "测试摘要：测试新闻"
    assert item.summary_model == "deepseek-v4-flash"


def test_disabled_summary_marks_items_without_calling_llm() -> None:
    settings = _settings()
    settings.llm_summary_enabled = False
    service = LLMService(settings, client=MockLLMClient())
    report = _report()

    service.summarize_report(report)

    assert report.blocks[0].items[0].summary_status == "disabled"
    assert report.blocks[0].items[0].llm_summary == ""


def test_answer_question_returns_citation() -> None:
    service = LLMService(_settings(), client=CitationClient())
    report = _report()

    answer = service.answer_question(report, "今天有什么新闻？")

    assert "测试新闻" in answer
    assert "https://example.com/1" in answer


def test_rate_limiter_rejects_after_daily_limit(tmp_path) -> None:
    limiter = LLMRateLimiter(daily_limit=2, minute_limit=10)
    limiter.check()
    limiter.record_success()
    limiter.check()
    limiter.record_success()

    with pytest.raises(LLMRateLimitError):
        limiter.check()

class RecordingClient(LLMClient):
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def chat(self, messages: list[dict[str, str]]) -> str:
        self.messages = messages
        return "中文测试回答"


def test_summary_prompt_requires_chinese() -> None:
    client = RecordingClient()
    service = LLMService(_settings(), client=client)

    service.summarize_item(_report().blocks[0].items[0])

    system = client.messages[0]["content"]
    assert "简体中文" in system
    assert "英文原文" in system


def test_answer_prompt_requires_chinese() -> None:
    client = RecordingClient()
    service = LLMService(_settings(), client=client)

    service.answer_question(_report(), "今天有什么新闻？")

    system = client.messages[0]["content"]
    assert "始终使用简体中文" in system
    assert "英文" in system