import httpx
import pytest

from assistant.sources.base import DataSourceError
from assistant.sources.github import GitHubTrendingSource

TRENDING_HTML = """
<html><body>
<article class="Box-row">
  <h2 class="h3 lh-condensed"><a href="/openai/evals">openai / evals</a></h2>
  <p class="col-9 color-fg-muted">An evaluation framework for LLMs.</p>
  <span itemprop="programmingLanguage" class="d-inline-flex">Python</span>
  <a href="/openai/evals/stargazers"><span>12,345</span></a>
</article>
<article class="Box-row">
  <h2 class="h3 lh-condensed"><a href="/pallets/flask">pallets / flask</a></h2>
  <p class="col-9 color-fg-muted">A lightweight WSGI web framework.</p>
  <span itemprop="programmingLanguage" class="d-inline-flex">Python</span>
  <a href="/pallets/flask/stargazers"><span>70,000</span></a>
</article>
</body></html>
"""


def test_github_source_parses_official_trending_page() -> None:
    source = GitHubTrendingSource(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=TRENDING_HTML)
            )
        )
    )

    result = source.fetch(limit=2)

    assert result.degraded is False
    assert result.mode == "official"
    assert len(result.items) == 2
    assert result.items[0].title == "openai/evals"
    assert result.items[0].url == "https://github.com/openai/evals"
    assert result.items[0].language == "Python"
    assert result.items[0].metadata["stars"] == 12345
    assert result.items[0].stars == 12345


def test_github_source_falls_back_to_search_api() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.github.com" in url:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "full_name": "torvalds/linux",
                            "description": "Linux kernel",
                            "html_url": "https://github.com/torvalds/linux",
                            "stargazers_count": 100000,
                            "language": "C",
                        }
                    ]
                },
            )
        return httpx.Response(200, text="<html><body>empty</body></html>")

    source = GitHubTrendingSource(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    result = source.fetch(limit=10)

    assert result.degraded is True
    assert result.mode == "search_api"
    assert len(result.items) == 1
    assert result.items[0].source == "GitHub Search API"
    assert "近似" in result.message


def test_github_source_raises_when_both_modes_fail() -> None:
    source = GitHubTrendingSource(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(500)
            )
        )
    )

    with pytest.raises(DataSourceError):
        source.fetch(limit=10)
NEW_TRENDING_HTML = """
<html><body>
<article class="Box-row">
  <h2 class="h3 lh-condensed"><a href="/tt-a1i/archify">tt-a1i / archify</a></h2>
  <p class="col-9 color-fg-muted">Architecture diagrams as HTML.</p>
  <span itemprop="programmingLanguage" class="d-inline-flex">JavaScript</span>
  <a href="/tt-a1i/archify/stargazers" data-view-component="true" class="tmp-mr-3 Link Link--muted d-inline-block"><svg aria-label="star" role="img" height="16" viewBox="0 0 16 16" width="16"><path d="M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.751.751 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Zm0 2.445L6.615 5.5a.75.75 0 0 1-.564.41l-3.097.45 2.24 2.184a.75.75 0 0 1 .216.664l-.528 3.084 2.769-1.456a.75.75 0 0 1 .698 0l2.77 1.456-.53-3.084a.75.75 0 0 1 .216-.664l2.24-2.183-3.096-.45a.75.75 0 0 1-.564-.41L8 2.694Z"></path></svg> 39,745</a>
</article>
</body></html>
"""


def test_github_source_parses_current_official_markup() -> None:
    source = GitHubTrendingSource(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=NEW_TRENDING_HTML)
            )
        )
    )

    result = source.fetch(limit=1)

    assert result.mode == "official"
    assert result.degraded is False
    assert result.items[0].stars == 39745
    assert result.items[0].metadata["stars"] == 39745


def test_github_source_falls_back_when_all_stars_are_zero() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "api.github.com" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "full_name": "fallback/repo",
                            "description": "fallback",
                            "html_url": "https://github.com/fallback/repo",
                            "stargazers_count": 123,
                            "language": "Python",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            text=NEW_TRENDING_HTML.replace("39,745", "0"),
        )

    source = GitHubTrendingSource(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    result = source.fetch(limit=10)

    assert result.mode == "search_api"
    assert result.degraded is True
    assert len(result.items) == 1
    assert result.items[0].source == "GitHub Search API"
    assert result.items[0].stars == 123