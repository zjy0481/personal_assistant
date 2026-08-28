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