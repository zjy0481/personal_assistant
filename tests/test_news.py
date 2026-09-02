from datetime import datetime, timezone

import json
import httpx

from assistant.sources.news import NEWS_FEEDS, NewsSource
from assistant.sources.rss import RssSource

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


def test_cctv_feed_uses_official_jsonp_domestic_url() -> None:
    feed = next(item for item in NEWS_FEEDS if item.key == "cctv")
    assert feed.format == "jsonp"
    assert feed.url.endswith("/china_1.jsonp")


def _rss_many(prefix: str, count: int = 6) -> str:
    items = []
    for index in range(1, count + 1):
        items.append(
            f"""  <item>
    <title>{prefix}新闻{index}</title>
    <link>https://example.com/{prefix}/{index}</link>
    <description>摘要{index}</description>
    <pubDate>Fri, 28 Aug 2026 0{index}:00:00 GMT</pubDate>
  </item>"""
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
{chr(10).join(items)}
</channel></rss>"""


def _jsonp_many(prefix: str, count: int = 6) -> str:
    rows = []
    for index in range(1, count + 1):
        rows.append(
            {
                "title": f"{prefix}新闻{index}",
                "url": f"https://example.com/{prefix}/{index}",
                "brief": f"摘要{index}",
                "focus_date": f"2026-08-28 {index + 8:02d}:00:00",
            }
        )
    return f"china({json.dumps({'data': {'list': rows}}, ensure_ascii=False)})"


def _quota_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "news.cctv.com/2019/07/gaiban/cmsdatainterface/page/china_1.jsonp" in url:
            return httpx.Response(200, text=_jsonp_many("央视新闻"))
        if "chinanews.com.cn" in url:
            return httpx.Response(200, text=_rss_many("中国新闻网"))
        if "feeds.npr.org" in url:
            return httpx.Response(200, text=_rss_many("NPR"))
        if "france24.com" in url:
            return httpx.Response(200, text=_rss_many("France24"))
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_news_source_applies_domestic_international_quotas() -> None:
    source = NewsSource(client=_quota_client())

    result = source.fetch(
        whitelist={"cctv", "chinanews", "npr", "france24"},
        since=SINCE,
        limit=10,
        domestic_limit=10,
        international_limit=10,
        max_per_source=5,
    )

    assert len(result.items) == 20
    assert sum(item.category == "国际" for item in result.items) == 10
    assert sum(item.category != "国际" for item in result.items) == 10
    counts: dict[str, int] = {}
    for item in result.items:
        key = str((item.metadata or {}).get("feed_key", ""))
        counts[key] = counts.get(key, 0) + 1
    assert max(counts.values()) == 5
    assert result.degraded is False
    assert result.message == ""


def test_rss_source_caps_each_feed_before_global_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "news.cctv.com/2019/07/gaiban/cmsdatainterface/page/china_1.jsonp" in url:
            return httpx.Response(200, text=_jsonp_many("央视新闻", count=20))
        if "feeds.npr.org" in url:
            return httpx.Response(200, text=_rss_many("NPR", count=20))
        return httpx.Response(404)

    source = RssSource(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    feeds = [
        next(item for item in NEWS_FEEDS if item.key == "cctv"),
        next(item for item in NEWS_FEEDS if item.key == "npr"),
    ]
    result = source.fetch(
        feeds=feeds,
        whitelist={"cctv", "npr"},
        since=SINCE,
        limit=20,
        per_source_limit=5,
    )

    counts = {
        str((item.metadata or {}).get("feed_key", ""))
        for item in result.items
    }
    assert counts == {"cctv", "npr"}
    assert len(result.items) == 10


def test_news_source_reports_international_quota_shortage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "people.com.cn" in str(request.url):
            return httpx.Response(200, text=_rss_many("人民网"))
        if "feeds.npr.org" in str(request.url):
            return httpx.Response(
                200,
                text=_rss(
                    "One NPR story",
                    "https://example.com/npr/1",
                    "Fri, 28 Aug 2026 01:00:00 GMT",
                ),
            )
        return httpx.Response(404)

    source = NewsSource(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    result = source.fetch(
        whitelist={"people", "npr"},
        since=SINCE,
        limit=10,
        domestic_limit=2,
        international_limit=2,
        max_per_source=5,
    )

    assert result.degraded is True
    assert "国际新闻配额未满足" in result.message
    assert sum(item.category != "国际" for item in result.items) == 2
    assert sum(item.category == "国际" for item in result.items) == 1
