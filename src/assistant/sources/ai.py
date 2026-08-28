"""AI industry news source over official and Chinese AI feeds."""

from collections.abc import Collection
from datetime import datetime

import httpx

from assistant.sources.rss import Feed, FeedResult, RssSource

AI_FEEDS = [
    Feed(
        key="openai",
        name="OpenAI",
        url="https://openai.com/news/rss.xml",
        language="en",
        category="产品发布",
    ),
    Feed(
        key="deepmind",
        name="Google DeepMind",
        url="https://deepmind.google/blog/rss.xml",
        language="en",
        category="研究",
    ),
    Feed(
        key="anthropic",
        name="Anthropic",
        url="https://www.anthropic.com/news/rss.xml",
        language="en",
        category="产品发布",
    ),
    Feed(
        key="huggingface",
        name="Hugging Face",
        url="https://huggingface.co/blog/feed.xml",
        language="en",
        category="开源",
    ),
    Feed(
        key="jiqizhixin",
        name="机器之心",
        url="https://www.jiqizhixin.com/rss",
        language="zh",
        category="中文 AI",
    ),
    Feed(
        key="qbitai",
        name="量子位",
        url="https://www.qbitai.com/feed",
        language="zh",
        category="中文 AI",
    ),
]


class AINewsSource:
    """Fetch AI industry feeds while isolating individual feed failures."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._rss = RssSource(client=client)

    def fetch(
        self,
        whitelist: Collection[str] | None = None,
        since: datetime | None = None,
        limit: int = 8,
    ) -> FeedResult:
        allowed = (
            whitelist
            if whitelist is not None
            else {feed.key for feed in AI_FEEDS}
        )
        return self._rss.fetch(
            feeds=AI_FEEDS,
            whitelist=allowed,
            since=since,
            limit=limit,
        )