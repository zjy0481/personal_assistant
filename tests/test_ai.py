from datetime import datetime, timezone

import httpx

from assistant.sources.ai import AINewsSource

SINCE = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)


def _rss(title: str, url: str, published_at: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>{title}</title>
    <link>{url}</link>
    <description>AI 动态摘要</description>
    <pubDate>{published_at}</pubDate>
  </item>
</channel></rss>"""


def test_ai_source_returns_categorized_items_with_links() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "openai.com" in url:
            return httpx.Response(
                200,
                text=_rss(
                    "OpenAI launches new model",
                    "https://openai.com/news/new-model",
                    "Fri, 28 Aug 2026 01:00:00 GMT",
                ),
            )
        return httpx.Response(
            200,
            text=_rss(
                "Hugging Face releases dataset",
                "https://huggingface.co/blog/dataset",
                "Fri, 28 Aug 2026 02:00:00 GMT",
            ),
        )

    source = AINewsSource(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    result = source.fetch(
        whitelist={"openai", "huggingface"},
        since=SINCE,
        limit=8,
    )

    assert len(result.items) == 2
    assert {item.source for item in result.items} == {
        "OpenAI",
        "Hugging Face",
    }
    assert {item.category for item in result.items} == {
        "产品发布",
        "开源",
    }
    assert all(item.url for item in result.items)


def test_ai_source_keeps_other_sources_when_one_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "openai.com" in str(request.url):
            return httpx.Response(500)
        return httpx.Response(
            200,
            text=_rss(
                "Hugging Face releases dataset",
                "https://huggingface.co/blog/dataset",
                "Fri, 28 Aug 2026 02:00:00 GMT",
            ),
        )

    source = AINewsSource(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    result = source.fetch(
        whitelist={"openai", "huggingface"},
        since=SINCE,
        limit=8,
    )

    assert [item.source for item in result.items] == ["Hugging Face"]
    assert result.source_statuses["openai"].startswith("failed")
    assert result.source_statuses["huggingface"] == "ok"