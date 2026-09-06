"""Tests for the V3 web search adapter and controlled page reader."""

import json
from dataclasses import asdict

import httpx
import pytest

from assistant.config import Settings
from assistant.web_search import (
    DeepSeekWebSearchAdapter,
    WebPageReadError,
    WebPageReader,
)


def _settings() -> Settings:
    return Settings(
        location="上海",
        timezone="Asia/Shanghai",
        llm_api_key="test-deepseek-key",
        web_search_model="deepseek-v4-flash",
    )


def test_deepseek_web_search_sends_responses_tool_and_returns_sources() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/responses")
        payload = json.loads(request.content)
        assert payload["tools"] == [{"type": "web_search"}]
        assert payload["model"] == "deepseek-v4-flash"
        return httpx.Response(
            200,
            json={
                "output_text": "今天值得关注的新闻是测试新闻。"
                "[测试新闻](https://example.com/news)",
                "output": [
                    {
                        "type": "web_search_call",
                        "url": "https://example.com/news",
                        "title": "测试新闻",
                    }
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = DeepSeekWebSearchAdapter(_settings(), client=client)

    result = adapter.search(
        "今天有什么值得关注？",
        "日报上下文：测试日报",
        max_rounds=1,
    )

    assert result.answer == (
        "今天值得关注的新闻是测试新闻。"
        "[测试新闻](https://example.com/news)"
    )
    assert [asdict(source) for source in result.sources] == [
        {"title": "测试新闻", "url": "https://example.com/news", "snippet": ""}
    ]


def test_page_reader_rejects_private_host() -> None:
    reader = WebPageReader(_settings())

    with pytest.raises(WebPageReadError):
        reader.read("http://127.0.0.1/private")


def test_page_reader_extracts_html_title_and_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "example.com"
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><head><title>示例页面</title></head>"
            "<body><p>这是正文内容。</p></body></html>",
        )

    reader = WebPageReader(
        _settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        resolver=lambda host: ["8.8.8.8"],
    )

    page = reader.read("https://example.com/article")

    assert page.url == "https://example.com/article"
    assert page.title == "示例页面"
    assert "这是正文内容" in page.text


def test_page_reader_rejects_non_http_scheme() -> None:
    reader = WebPageReader(_settings())

    with pytest.raises(WebPageReadError):
        reader.read("file:///etc/passwd")


def test_page_reader_rejects_configured_blocked_host() -> None:
    settings = _settings()
    settings.web_blocked_hosts = ["example.com"]
    reader = WebPageReader(settings)

    with pytest.raises(WebPageReadError, match="禁止访问"):
        reader.read("https://example.com/article")


def test_page_reader_rejects_redirect_to_private_host() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "http://10.0.0.5/private"},
        )

    reader = WebPageReader(
        _settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        resolver=lambda host: ["8.8.8.8"],
    )

    with pytest.raises(WebPageReadError):
        reader.read("https://example.com/article")


def test_page_reader_caches_result_for_ttl() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-type": "text/plain; charset=utf-8"},
            text="缓存正文",
        )

    reader = WebPageReader(
        _settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        resolver=lambda host: ["8.8.8.8"],
    )

    first = reader.read("https://example.com/article")
    second = reader.read("https://example.com/article")

    assert first == second
    assert calls == 1


def test_deepseek_web_search_stream_yields_deltas_and_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                'data: {"type":"response.output_text.delta","delta":"联"}\n\n'
                'data: {"type":"response.output_text.delta","delta":"网答案"}\n\n'
                'data: {"type":"response.completed","response":{"output_text":"联网答案",'
                '"output":[{"type":"web_search_call","url":"https://example.com/news",'
                '"title":"来源"}]}}\n\n'
            ),
        )

    adapter = DeepSeekWebSearchAdapter(
        _settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    events = list(
        adapter.search_stream(
            "今天有什么新闻？",
            "日报上下文",
            max_rounds=1,
        )
    )

    assert ("delta", {"text": "联"}) in events
    assert ("delta", {"text": "网答案"}) in events
    result = next(payload for event, payload in events if event == "result")
    assert result["answer"] == "联网答案"
    assert result["sources"][0]["url"] == "https://example.com/news"
