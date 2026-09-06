"""Tests for the V3 web Q&A orchestration module."""

from datetime import datetime
from zoneinfo import ZoneInfo

from assistant.config import Settings
from assistant.models import ContentBlock, ContentItem, Report
from assistant.web_qa import WebQAService
from assistant.web_search import WebPage, WebSearchAnswer, WebSource


def _report() -> Report:
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
                items=[
                    ContentItem(
                        title="测试新闻",
                        url="https://example.com/1",
                        source="测试源",
                    )
                ],
            )
        ],
    )


class FakeSearchAdapter:
    def __init__(self, answer: str = "联网答案 [来源](https://example.com/news)"):
        self.answer = answer
        self.calls = 0

    def search(self, question: str, context: str, max_rounds: int = 2):
        self.calls += 1
        self.last_question = question
        return WebSearchAnswer(
            answer=self.answer,
            sources=[WebSource("来源", "https://example.com/news")],
            search_calls=1,
        )


class FakePageReader:
    def __init__(self, text: str = "页面正文内容"):
        self.text = text
        self.calls = 0

    def read(self, url: str) -> WebPage:
        self.calls += 1
        self.last_url = url
        return WebPage(url=url, title="页面标题", text=self.text)


class FakeLLMService:
    def __init__(self, answer: str = "日报离线答案"):
        self.answer = answer
        self.calls = 0

    def answer_question(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        self.calls += 1
        self.last_question = question
        return self.answer

    def answer_question_with_context(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]] | None = None,
        extra_context: str = "",
    ) -> str:
        self.calls += 1
        self.last_question = question
        self.last_context = extra_context
        return self.answer


def test_real_time_question_uses_search_and_returns_sources() -> None:
    settings = Settings(
        location="上海",
        timezone="Asia/Shanghai",
        web_search_enabled=True,
        web_daily_limit=10,
        llm_api_key="test-key",
    )
    search = FakeSearchAdapter()
    llm = FakeLLMService()
    service = WebQAService(
        settings,
        llm_service=llm,
        search_adapter=search,
        page_reader=FakePageReader(),
    )

    result = service.answer_question(_report(), "今天有什么值得关注？", mode="auto")

    assert result.used_web is True
    assert result.status == "ok"
    assert "联网" in result.answer or "来源" in result.answer
    assert result.citations[0].url == "https://example.com/news"
    assert search.calls == 1
    assert llm.calls == 0


def test_user_url_reads_page_and_passes_extra_context() -> None:
    settings = Settings(
        location="上海",
        timezone="Asia/Shanghai",
        web_search_enabled=True,
        web_daily_limit=10,
        llm_api_key="test-key",
    )
    reader = FakePageReader()
    llm = FakeLLMService(answer="根据页面正文回答")
    service = WebQAService(
        settings,
        llm_service=llm,
        search_adapter=FakeSearchAdapter(),
        page_reader=reader,
    )

    result = service.answer_question(
        _report(),
        "请阅读 https://example.com/article",
        mode="auto",
    )

    assert result.used_web is True
    assert result.status == "ok"
    assert reader.calls == 1
    assert "页面正文内容" in llm.last_context
    assert result.citations[0].url == "https://example.com/article"


def test_offline_mode_never_calls_web_modules() -> None:
    settings = Settings(
        location="上海",
        timezone="Asia/Shanghai",
        web_search_enabled=True,
        web_daily_limit=10,
        llm_api_key="test-key",
    )
    search = FakeSearchAdapter()
    reader = FakePageReader()
    llm = FakeLLMService()
    service = WebQAService(
        settings,
        llm_service=llm,
        search_adapter=search,
        page_reader=reader,
    )

    result = service.answer_question(
        _report(),
        "不联网，今天有什么新闻？",
        mode="auto",
    )

    assert result.used_web is False
    assert result.status == "offline"
    assert search.calls == 0
    assert reader.calls == 0
    assert llm.calls == 1


def test_local_question_without_time_signal_stays_offline() -> None:
    settings = Settings(
        location="上海",
        timezone="Asia/Shanghai",
        web_search_enabled=True,
        web_daily_limit=10,
        llm_api_key="test-key",
    )
    search = FakeSearchAdapter()
    llm = FakeLLMService()
    service = WebQAService(
        settings,
        llm_service=llm,
        search_adapter=search,
        page_reader=FakePageReader(),
    )

    result = service.answer_question(
        _report(),
        "昨天日报里的天气如何？",
        mode="auto",
    )

    assert result.status == "offline"
    assert search.calls == 0
    assert llm.calls == 1


def test_force_mode_searches_even_without_time_signal() -> None:
    settings = Settings(
        location="上海",
        timezone="Asia/Shanghai",
        web_search_enabled=True,
        web_daily_limit=10,
        llm_api_key="test-key",
    )
    search = FakeSearchAdapter()
    service = WebQAService(
        settings,
        llm_service=FakeLLMService(),
        search_adapter=search,
        page_reader=FakePageReader(),
    )

    result = service.answer_question(
        _report(),
        "查一下这个问题",
        mode="force",
    )

    assert result.used_web is True
    assert search.calls == 1


def test_search_failure_retries_then_falls_back() -> None:
    class FailingSearchAdapter:
        calls = 0

        def search(self, question, context, max_rounds=2):
            self.calls += 1
            raise RuntimeError("搜索服务不可用")

    settings = Settings(
        location="上海",
        timezone="Asia/Shanghai",
        web_search_enabled=True,
        web_daily_limit=10,
        llm_api_key="test-key",
    )
    failure = FailingSearchAdapter()
    llm = FakeLLMService()
    service = WebQAService(
        settings,
        llm_service=llm,
        search_adapter=failure,
        page_reader=FakePageReader(),
    )

    result = service.answer_question(
        _report(),
        "今天有什么新闻？",
        mode="auto",
    )

    assert result.status == "failed"
    assert "联网检索失败" in result.answer
    assert llm.calls == 1


def test_daily_limit_falls_back_to_offline() -> None:
    settings = Settings(
        location="上海",
        timezone="Asia/Shanghai",
        web_search_enabled=True,
        web_daily_limit=1,
        llm_api_key="test-key",
    )
    search = FakeSearchAdapter()
    llm = FakeLLMService()
    service = WebQAService(
        settings,
        llm_service=llm,
        search_adapter=search,
        page_reader=FakePageReader(),
    )

    first = service.answer_question(_report(), "今天有什么新闻？", mode="auto")
    second = service.answer_question(_report(), "今天有什么新闻？", mode="auto")

    assert first.status == "ok"
    assert second.status == "limited"
    assert "今日联网问答上限" in second.answer


def test_disabled_web_search_returns_disabled_status() -> None:
    settings = Settings(
        location="上海",
        timezone="Asia/Shanghai",
        web_search_enabled=False,
        web_daily_limit=10,
        llm_api_key="test-key",
    )
    search = FakeSearchAdapter()
    llm = FakeLLMService()
    service = WebQAService(
        settings,
        llm_service=llm,
        search_adapter=search,
        page_reader=FakePageReader(),
    )

    result = service.answer_question(_report(), "今天有什么新闻？", mode="auto")

    assert result.status == "disabled"
    assert search.calls == 0
    assert llm.calls == 1


def test_stream_events_yield_deltas_and_final_result() -> None:
    class StreamingSearchAdapter:
        def search_stream(self, question, context, max_rounds=2):
            yield ("delta", {"text": "联"})
            yield ("delta", {"text": "网答案"})
            yield (
                "result",
                {
                    "answer": "联网答案",
                    "sources": [
                        {"title": "来源", "url": "https://example.com/2"}
                    ],
                },
            )

    settings = Settings(
        location="上海",
        timezone="Asia/Shanghai",
        web_search_enabled=True,
        web_daily_limit=10,
        llm_api_key="test-key",
    )
    service = WebQAService(
        settings,
        llm_service=FakeLLMService(),
        search_adapter=StreamingSearchAdapter(),
        page_reader=FakePageReader(),
    )

    events = list(
        service.answer_question_events(
            _report(),
            "今天有什么新闻？",
            mode="auto",
        )
    )

    event_names = [event.event for event in events]
    assert "delta" in event_names
    assert "result" in event_names
    result = next(event for event in events if event.event == "result")
    assert result.data["answer"] == "联网答案"
    assert result.data["citations"][0]["url"] == "https://example.com/2"
