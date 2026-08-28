"""GitHub Trending primary parser and Search API fallback."""

import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from assistant.models import ContentItem
from assistant.sources.base import DataSourceError

_ARTICLE_RE = re.compile(r"<article\b.*?</article>", re.IGNORECASE | re.DOTALL)
_REPO_RE = re.compile(
    r'<h2\b[^>]*>\s*<a\b[^>]*href="/([^"]+)"',
    re.IGNORECASE | re.DOTALL,
)
_DESCRIPTION_RE = re.compile(
    r'<p\b[^>]*>(.*?)</p>',
    re.IGNORECASE | re.DOTALL,
)
_LANGUAGE_RE = re.compile(
    r'itemprop="programmingLanguage"[^>]*>([^<]+)',
    re.IGNORECASE,
)
_STARS_RE = re.compile(
    r'href="[^"]*stargazers[^"]*"[^>]*>\s*<span[^>]*>([\d,]+)',
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class GitHubTrendingResult:
    """Trending items plus the mode used to obtain them."""

    items: list[ContentItem] = field(default_factory=list)
    degraded: bool = False
    mode: str = "official"
    message: str = ""


def _strip_html(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


class GitHubTrendingSource:
    """Use github.com/trending first, then approximate with Search API."""

    OFFICIAL_URL = "https://github.com/trending"
    SEARCH_URL = "https://api.github.com/search/repositories"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            timeout=10.0,
            follow_redirects=True,
        )

    def fetch(
        self,
        limit: int = 10,
        now: datetime | None = None,
    ) -> GitHubTrendingResult:
        now = now or datetime.now(timezone.utc)
        try:
            items = self._fetch_official(limit)
            return GitHubTrendingResult(items=items, mode="official")
        except Exception as official_error:
            try:
                items = self._fetch_search(now, limit)
            except Exception as search_error:
                raise DataSourceError(
                    "GitHub Trending 获取失败：official="
                    f"{official_error}；search={search_error}"
                ) from search_error
            return GitHubTrendingResult(
                items=items,
                degraded=True,
                mode="search_api",
                message="使用 GitHub Search API 近似榜单，非官方按周口径",
            )

    def _fetch_official(self, limit: int) -> list[ContentItem]:
        response = self.client.get(
            self.OFFICIAL_URL,
            params={"since": "weekly"},
            headers={"User-Agent": "personal-assistant/0.1"},
        )
        response.raise_for_status()

        items: list[ContentItem] = []
        articles = _ARTICLE_RE.findall(response.text)
        if not articles:
            raise DataSourceError("GitHub Trending 页面结构未识别到榜单")

        for article in articles:
            repo_match = _REPO_RE.search(article)
            if not repo_match:
                continue
            path = repo_match.group(1).split("?")[0].strip("/")
            parts = path.split("/")
            if len(parts) < 2:
                continue
            owner, repo = parts[0], parts[1]

            description_match = _DESCRIPTION_RE.search(article)
            language_match = _LANGUAGE_RE.search(article)
            stars_match = _STARS_RE.search(article)
            stars = (
                int(stars_match.group(1).replace(",", ""))
                if stars_match
                else 0
            )

            items.append(
                ContentItem(
                    title=f"{owner}/{repo}",
                    url=f"https://github.com/{owner}/{repo}",
                    source="GitHub Trending",
                    summary=_strip_html(
                        description_match.group(1)
                        if description_match
                        else ""
                    ),
                    language=(
                        language_match.group(1).strip()
                        if language_match
                        else ""
                    ),
                    category="github_trending",
                    stars=stars,
                    metadata={
                        "stars": stars,
                        "mode": "official",
                    },
                )
            )
            if len(items) >= limit:
                break

        return items

    def _fetch_search(self, now: datetime, limit: int) -> list[ContentItem]:
        week_start = (now - timedelta(days=7)).date().isoformat()
        response = self.client.get(
            self.SEARCH_URL,
            params={
                "q": f"created:>{week_start}",
                "sort": "stars",
                "order": "desc",
                "per_page": limit,
            },
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "personal-assistant/0.1",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("items") or []
        if not items:
            raise DataSourceError("GitHub Search API 未返回榜单")

        return [
            ContentItem(
                title=item.get("full_name", ""),
                url=item.get("html_url", ""),
                source="GitHub Search API",
                summary=item.get("description", "") or "",
                language=item.get("language", "") or "",
                category="github_trending",
                stars=item.get("stargazers_count", 0),
                metadata={
                    "stars": item.get("stargazers_count", 0),
                    "mode": "search_api",
                },
            )
            for item in items[:limit]
        ]