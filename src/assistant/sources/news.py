"""Current affairs news source over configured public RSS/API feeds."""

from collections.abc import Collection
from datetime import datetime

import httpx

from assistant.sources.rss import Feed, FeedResult, RssSource

NEWS_FEEDS = [
    Feed(
        key="xinhua",
        name="新华社",
        url="https://www.news.cn/rss/",
        language="zh",
        category="时事",
    ),
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
        key="cctv",
        name="央视新闻",
        url="https://news.cctv.com/rss/",
        language="zh",
        category="时事",
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
    ) -> FeedResult:
        allowed = (
            whitelist
            if whitelist is not None
            else {feed.key for feed in NEWS_FEEDS}
        )
        return self._rss.fetch(
            feeds=NEWS_FEEDS,
            whitelist=allowed,
            since=since,
            limit=limit,
        )