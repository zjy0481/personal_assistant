"""Current affairs news source over configured public RSS/API feeds."""

from collections import defaultdict
from collections.abc import Collection
from datetime import datetime, timezone

import httpx

from assistant.models import ContentItem
from assistant.sources.rss import Feed, FeedResult, RssSource

_NEWS_DEFAULT_MIN = datetime.min.replace(tzinfo=timezone.utc)

NEWS_FEEDS = [
    Feed(
        key="xinhua",
        name="新华社",
        url="https://www.news.cn/rss/",
        language="zh",
        category="时事",
    ),
    # 人民网 RSS 已停更（内容停留在 2025 年），保留定义但默认白名单不启用。
    Feed(
        key="people",
        name="人民网",
        url="http://www.people.com.cn/rss/politics.xml",
        language="zh",
        category="时事",
    ),
    Feed(
        key="thepaper",
        name="澎湃新闻",
        url="https://feed.thepaper.cn/",
        language="zh",
        category="时事",
    ),
    Feed(
        key="chinanews",
        name="中国新闻网",
        url="https://www.chinanews.com.cn/rss/china.xml",
        language="zh",
        category="时事",
    ),
    Feed(
        key="npr",
        name="NPR",
        url="https://feeds.npr.org/1001/rss.xml",
        language="en",
        category="国际",
    ),
    Feed(
        key="france24",
        name="France24",
        url="https://www.france24.com/en/rss",
        language="en",
        category="国际",
    ),
    # 央视网官方国内频道 JSONP 接口，替代已失效的旧版 RSS。
    Feed(
        key="cctv",
        name="央视新闻",
        url="https://news.cctv.com/2019/07/gaiban/cmsdatainterface/page/china_1.jsonp",
        language="zh",
        category="时事",
        format="jsonp",
    ),
    Feed(
        key="reuters",
        name="Reuters",
        url="https://feeds.reuters.com/reuters/worldNews",
        language="en",
        category="国际",
    ),
    Feed(
        key="ap",
        name="AP",
        url="https://feeds.apnews.com/apf-topnews",
        language="en",
        category="国际",
    ),
    Feed(
        key="bbc",
        name="BBC News",
        url="https://feeds.bbci.co.uk/news/rss.xml",
        language="en",
        category="国际",
    ),
]


class NewsSource:
    """Fetch public news feeds while keeping failures isolated by feed."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._rss = RssSource(client=client)

    def fetch(
        self,
        whitelist: Collection[str] | None = None,
        since: datetime | None = None,
        limit: int = 10,
        *,
        domestic_limit: int | None = None,
        international_limit: int | None = None,
        max_per_source: int | None = None,
    ) -> FeedResult:
        allowed = (
            whitelist
            if whitelist is not None
            else {feed.key for feed in NEWS_FEEDS}
        )
        if domestic_limit is None and international_limit is None:
            return self._rss.fetch(
                feeds=NEWS_FEEDS,
                whitelist=allowed,
                since=since,
                limit=limit,
            )

        raw_limit = max(
            limit,
            (domestic_limit or 0) + (international_limit or 0),
            (max_per_source or 1) * len(NEWS_FEEDS),
        )
        result = self._rss.fetch(
            feeds=NEWS_FEEDS,
            whitelist=allowed,
            since=since,
            limit=raw_limit,
            per_source_limit=max_per_source or 1,
        )
        result.items, result.message = _select_news_quotas(
            result.items,
            domestic_limit=domestic_limit or 0,
            international_limit=international_limit or 0,
            max_per_source=max_per_source or 1,
        )
        if result.message:
            result.degraded = True
        return result


def _select_news_quotas(
    items: list[ContentItem],
    *,
    domestic_limit: int,
    international_limit: int,
    max_per_source: int,
) -> tuple[list[ContentItem], str]:
    grouped: dict[str, list[ContentItem]] = defaultdict(list)
    for item in items:
        feed_key = str((item.metadata or {}).get("feed_key", ""))
        grouped[feed_key].append(item)

    candidates: list[ContentItem] = []
    for source_items in grouped.values():
        source_items.sort(
            key=lambda item: item.published_at or _NEWS_DEFAULT_MIN,
            reverse=True,
        )
        candidates.extend(source_items[:max_per_source])

    domestic: list[ContentItem] = []
    international: list[ContentItem] = []
    for item in candidates:
        target = international if item.category == "国际" else domestic
        target.append(item)
    domestic.sort(
        key=lambda item: item.published_at or _NEWS_DEFAULT_MIN,
        reverse=True,
    )
    international.sort(
        key=lambda item: item.published_at or _NEWS_DEFAULT_MIN,
        reverse=True,
    )

    selected_domestic = domestic[:domestic_limit]
    selected_international = international[:international_limit]
    selected = selected_domestic + selected_international
    selected.sort(
        key=lambda item: item.published_at or _NEWS_DEFAULT_MIN,
        reverse=True,
    )

    shortage_messages: list[str] = []
    if len(selected_domestic) < domestic_limit:
        shortage_messages.append(
            f"国内新闻配额未满足（{len(selected_domestic)}/{domestic_limit}）"
        )
    if len(selected_international) < international_limit:
        shortage_messages.append(
            f"国际新闻配额未满足（{len(selected_international)}/{international_limit}）"
        )
    return selected, "；".join(shortage_messages)
