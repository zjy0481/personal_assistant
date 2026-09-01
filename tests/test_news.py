from datetime import datetime, timezone

import httpx

from assistant.sources.news import NEWS_FEEDS, NewsSource

SINCE = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)


def _rss(
    title: str,
    url: str,
    published_at: str,
    description: str = "摘要",
) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>{title}</title>
    <link>{url}</link>
    <description>{description}</description>
    <pubDate>{published_at}</pubDate>
  </item>
</channel></rss>"""


def _client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if "people.com.cn" in str(request.url):
            return httpx.Response(
                200,
                text=_rss(
                    "人民网新闻",
                    "https://example.com/people/1",
                    "Fri, 28 Aug 2026 01:00:00 GMT",
                ),
            )
        if "bbci.co.uk" in str(request.url):
            return httpx.Response(
                200,
                text=_rss(
                    "BBC News",
                    "https://example.com/bbc/1",
                    "Fri, 28 Aug 2026 02:00:00 GMT",
                ),
            )
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_news_source_returns_allowed_items_with_traceable_links() -> None:
    source = NewsSource(client=_client())

    result = source.fetch(
        whitelist={"people", "bbc"},
        since=SINCE,
        limit=10,
    )

    assert {item.source for item in result.items} == {"人民网", "BBC News"}
    assert all(item.url for item in result.items)
    assert result.source_statuses == {
        "people": "ok",
        "bbc": "ok",
    }


def test_news_source_keeps_other_sources_when_one_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "people.com.cn" in str(request.url):
            return httpx.Response(500)
        return httpx.Response(
            200,
            text=_rss(
                "BBC News",
                "https://example.com/bbc/1",
                "Fri, 28 Aug 2026 02:00:00 GMT",
            ),
        )

    source = NewsSource(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    result = source.fetch(
        whitelist={"people", "bbc"},
        since=SINCE,
        limit=10,
    )

    assert [item.source for item in result.items] == ["BBC News"]
    assert result.source_statuses["people"].startswith("failed")
    assert result.source_statuses["bbc"] == "ok"


def test_news_source_deduplicates_and_limits_items() -> None:
    source = NewsSource(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    text=_rss(
                        "重复新闻",
                        "https://example.com/duplicate",
                        "Fri, 28 Aug 2026 02:00:00 GMT",
                    ),
                )
            )
        )
    )

    result = source.fetch(
        whitelist={"people"},
        since=SINCE,
        limit=1,
    )

    assert len(result.items) == 1
    assert result.items[0].url == "https://example.com/duplicate"

def test_news_source_drops_items_older_than_since() -> None:
    xml = _rss(
        "过期新闻",
        "https://example.com/old",
        "Thu, 27 Aug 2026 23:00:00 GMT",
    )
    source = NewsSource(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=xml)
            )
        )
    )

    result = source.fetch(
        whitelist={"people"},
        since=SINCE,
        limit=10,
    )

    assert result.items == []

def test_chinanews_feed_uses_parseable_xml_url() -> None:
    feed = next(item for item in NEWS_FEEDS if item.key == "chinanews")
    assert feed.url == "https://www.chinanews.com.cn/rss/china.xml"