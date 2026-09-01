import threading
import time
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
    LLMError,
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
class _ConcurrencyClient(LLMClient):
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def chat(self, messages: list[dict[str, str]]) -> str:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        with self.lock:
            self.active -= 1
        return "并发摘要"


def test_summarize_report_respects_item_budget() -> None:
    settings = _settings()
    settings.llm_max_items = 1
    report = _report()
    report.blocks[0].items.append(
        ContentItem(title="第二条新闻", url="https://example.com/2", source="人民网")
    )
    service = LLMService(settings, client=MockLLMClient())

    service.summarize_report(report)

    assert report.blocks[0].items[0].summary_status == "ok"
    assert report.blocks[0].items[1].summary_status == ""


def test_summarize_report_uses_bounded_concurrency() -> None:
    client = _ConcurrencyClient()
    report = _report()
    for index in range(1, 5):
        report.blocks[0].items.append(
            ContentItem(
                title=f"并发新闻{index}",
                url=f"https://example.com/{index}",
                source="人民网",
            )
        )
    service = LLMService(_settings(), client=client)

    service.summarize_report(report)

    assert client.max_active == 3
    assert all(item.summary_status == "ok" for item in report.blocks[0].items)
class _FlakyLLMClient(LLMClient):
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        if self.calls == 1:
            raise LLMError("transient failure")
        return "重试摘要"


def test_summarize_report_retries_failed_item_once() -> None:
    client = _FlakyLLMClient()
    report = _report()
    service = LLMService(_settings(), client=client)

    service.summarize_report(report)

    assert client.calls == 2
    assert report.blocks[0].items[0].summary_status == "ok"
    assert report.blocks[0].items[0].llm_summary == "重试摘要"