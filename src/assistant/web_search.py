"""V3 web search adapter and controlled public page reader."""

from __future__ import annotations

import html
import ipaddress
import json
import logging
import re
import socket
import time
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from threading import Lock
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import httpx

from assistant.config import Settings

logger = logging.getLogger(__name__)

_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_URL_RE = re.compile(r"https?://[^\s，。；、]+")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "0.0.0.0",
}


class WebSearchError(RuntimeError):
    """Raised when the web search backend cannot complete a search."""


class WebPageReadError(RuntimeError):
    """Raised when a public page cannot be read safely."""


@dataclass(frozen=True)
class WebSource:
    """One citeable source returned by a search or page read."""

    title: str
    url: str
    snippet: str = ""


@dataclass(frozen=True)
class WebSearchAnswer:
    """Answer and sources returned by a web search adapter."""

    answer: str
    sources: list[WebSource] = field(default_factory=list)
    search_calls: int = 1


@dataclass(frozen=True)
class WebPage:
    """Extracted text from one public web page."""

    url: str
    title: str
    text: str
    truncated: bool = False


class WebSearchAdapter:
    """Search adapter seam used by the web Q&A orchestration module."""

    def search(
        self,
        question: str,
        context: str,
        max_rounds: int = 2,
    ) -> WebSearchAnswer:
        raise NotImplementedError


class DeepSeekWebSearchAdapter(WebSearchAdapter):
    """DeepSeek Responses API adapter with server-side web_search."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        timeout_seconds: int = 30,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self.api_key = api_key or (settings.llm_api_key if settings else "")
        self.base_url = (
            base_url
            or (settings.llm_base_url if settings else "https://api.deepseek.com")
        ).rstrip("/")
        self.model = (
            model
            or (settings.web_search_model if settings else "")
            or (settings.llm_model if settings else "deepseek-v4-flash")
        )
        self.timeout_seconds = (
            timeout_seconds
            or (settings.llm_timeout_seconds if settings else 30)
        )
        self.client = client or httpx.Client(
            timeout=self.timeout_seconds,
            follow_redirects=True,
        )

    def search(
        self,
        question: str,
        context: str,
        max_rounds: int = 2,
    ) -> WebSearchAnswer:
        if not self.api_key:
            raise WebSearchError("DeepSeek API Key 未配置")

        last_answer = ""
        sources: list[WebSource] = []
        calls = 0
        for _ in range(max(1, min(max_rounds, 5))):
            calls += 1
            answer, round_sources = self._call(
                question=question,
                context=context,
            )
            last_answer = answer or last_answer
            sources.extend(round_sources)
            sources = _unique_sources(sources)
            if answer and sources:
                break
        return WebSearchAnswer(
            answer=last_answer,
            sources=sources,
            search_calls=calls,
        )

    def search_stream(
        self,
        question: str,
        context: str,
        max_rounds: int = 2,
    ) -> Any:
        """Stream DeepSeek web search deltas, sources and a final result."""
        if not self.api_key:
            raise WebSearchError("DeepSeek API Key 未配置")
        instructions = (
            "你是个人日报助手。请始终使用简体中文回答。"
            "使用 web_search 检索最新或实时信息；只使用搜索返回的事实。"
            "回答必须为事实引用来源，格式为 [标题](URL)。"
            "如果搜索没有可靠来源，明确说明无法确认，不要编造。"
        )
        payload = {
            "model": self.model,
            "instructions": instructions,
            "input": f"本地上下文：\n{context}\n\n用户问题：{question}",
            "tools": [{"type": "web_search"}],
            "tool_choice": "auto",
            "stream": True,
            "temperature": 0.2,
            "max_output_tokens": 2000,
        }
        with self.client.stream(
            "POST",
            f"{self.base_url}/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        ) as response:
            response.raise_for_status()
            answer_parts: list[str] = []
            sources: list[WebSource] = []
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                event_type = str(data.get("type") or data.get("event") or "")
                if event_type == "response.output_text.delta":
                    delta = str(data.get("delta") or "")
                    if delta:
                        answer_parts.append(delta)
                        yield ("delta", {"text": delta})
                    continue
                final = data.get("response") or data
                if event_type in {
                    "response.completed",
                    "response.incomplete",
                    "response.failed",
                }:
                    answer = _extract_answer(final)
                    if not answer:
                        answer = "".join(answer_parts)
                    sources = _extract_sources(final, answer)
                    yield (
                        "result",
                        {
                            "answer": answer,
                            "sources": [asdict(item) for item in sources],
                        },
                    )
            if not answer_parts and not sources:
                raise WebSearchError("联网搜索未返回内容")

    def _call(self, question: str, context: str) -> tuple[str, list[WebSource]]:
        instructions = (
            "你是个人日报助手。请始终使用简体中文回答。"
            "使用 web_search 检索最新或实时信息；只使用搜索返回的事实。"
            "回答必须为事实引用来源，格式为 [标题](URL)。"
            "如果搜索没有可靠来源，明确说明无法确认，不要编造。"
        )
        payload = {
            "model": self.model,
            "instructions": instructions,
            "input": f"本地上下文：\n{context}\n\n用户问题：{question}",
            "tools": [{"type": "web_search"}],
            "tool_choice": "auto",
            "stream": False,
            "temperature": 0.2,
            "max_output_tokens": 2000,
        }
        try:
            response = self.client.post(
                f"{self.base_url}/responses",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.warning("DeepSeek web_search 请求失败：%s", exc)
            raise WebSearchError("联网搜索失败") from exc

        answer = _extract_answer(data)
        sources = _extract_sources(data, answer)
        return answer, _unique_sources(sources)


class WebPageReader:
    """Read and extract text from public HTTP(S) pages with SSRF protection."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        resolver: Callable[[str], list[str]] | None = None,
        cache_ttl_seconds: int | None = None,
        max_bytes: int | None = None,
    ) -> None:
        self.settings = settings
        self.timeout_seconds = settings.web_fetch_timeout_seconds
        self.cache_ttl_seconds = (
            settings.web_page_cache_ttl_seconds
            if cache_ttl_seconds is None
            else cache_ttl_seconds
        )
        self.max_bytes = max_bytes or settings.web_page_max_bytes
        self.blocked_hosts = {
            host.strip().lower() for host in settings.web_blocked_hosts
        }
        self._resolver = resolver or self._resolve
        proxy = settings.http_proxy or settings.https_proxy or None
        self.client = client or httpx.Client(
            timeout=self.timeout_seconds,
            follow_redirects=False,
            proxy=proxy,
        )
        self._cache: dict[str, tuple[float, WebPage]] = {}
        self._cache_lock = Lock()

    def read(self, url: str) -> WebPage:
        current_url = url.strip()
        cached = self._get_cached(current_url)
        if cached is not None:
            return cached

        redirects = 0
        while True:
            self._validate_url(current_url)
            response = self.client.get(
                current_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; PersonalAssistant/0.1)"
                    ),
                    "Accept": "text/html,text/plain,text/markdown,*/*",
                },
            )
            if response.status_code in (301, 302, 303, 307, 308):
                redirects += 1
                if redirects > 5:
                    raise WebPageReadError("网页重定向次数过多")
                location = response.headers.get("location", "")
                if not location:
                    raise WebPageReadError("网页重定向缺少 Location")
                current_url = urljoin(current_url, location)
                continue
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if not _is_supported_content_type(content_type):
                raise WebPageReadError(
                    f"不支持的网页内容类型: {content_type or 'unknown'}"
                )
            body = response.content
            truncated = len(body) > self.max_bytes
            if truncated:
                body = body[: self.max_bytes]
            text, title = _extract_page(body, content_type)
            page = WebPage(
                url=current_url,
                title=title,
                text=text,
                truncated=truncated,
            )
            self._put_cache(current_url, page)
            return page

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise WebPageReadError("仅允许访问 http(s) 网页")
        host = (parsed.hostname or "").strip()
        if not host or host.lower() in _BLOCKED_HOSTS:
            raise WebPageReadError("目标主机不受支持")
        if host.lower() in self.blocked_hosts:
            raise WebPageReadError("目标主机已被配置为禁止访问")
        if _is_ip_address(host):
            _assert_public_ip(host)
            return
        try:
            addresses = self._resolver(host)
        except Exception as exc:
            raise WebPageReadError("无法解析目标主机") from exc
        if not addresses:
            raise WebPageReadError("目标主机无法解析")
        for address in addresses:
            _assert_public_ip(address)

    @staticmethod
    def _resolve(host: str) -> list[str]:
        infos = socket.getaddrinfo(
            host,
            None,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        return list(dict.fromkeys(info[4][0] for info in infos))

    def _get_cached(self, url: str) -> WebPage | None:
        with self._cache_lock:
            item = self._cache.get(url)
            if item is None:
                return None
            saved_at, page = item
            if self.cache_ttl_seconds <= 0:
                return None
            if time.monotonic() - saved_at > self.cache_ttl_seconds:
                self._cache.pop(url, None)
                return None
            return page

    def _put_cache(self, url: str, page: WebPage) -> None:
        with self._cache_lock:
            self._cache[url] = (time.monotonic(), page)


def detect_web_mode(question: str) -> str:
    """Return ``offline``, ``force`` or ``auto`` from the user's wording."""
    text = question.strip().lower()
    if any(word in text for word in ("不联网", "离线", "不搜索")):
        return "offline"
    if any(word in text for word in ("联网", "搜索", "查一下")):
        return "force"
    return "auto"


def extract_urls(text: str) -> list[str]:
    """Return unique public URLs found in one piece of user text."""
    found: list[str] = []
    seen: set[str] = set()
    for match in _URL_RE.findall(text):
        url = match.rstrip("。；，、）)]}>")
        if url not in seen:
            seen.add(url)
            found.append(url)
    return found


def unique_sources(sources: list[WebSource]) -> list[WebSource]:
    """Return sources deduplicated by normalized URL."""
    return _unique_sources(sources)


def _unique_sources(sources: list[WebSource]) -> list[WebSource]:
    result: list[WebSource] = []
    seen: set[str] = set()
    for source in sources:
        key = (source.title or "").strip() + "|" + source.url.strip()
        if key in seen:
            continue
        seen.add(key)
        result.append(source)
    return result


def _extract_answer(payload: dict[str, Any]) -> str:
    answer = str(payload.get("output_text") or "").strip()
    if answer:
        return _strip_links_only(answer)

    parts: list[str] = []
    for item in payload.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for content in item.get("content", []) or []:
                if isinstance(content, dict) and content.get("type") == "output_text":
                    parts.append(str(content.get("text") or ""))
        elif item.get("type") == "reasoning":
            parts.append(str(item.get("content") or ""))
    return _strip_links_only("\n".join(parts)).strip()


def _strip_links_only(text: str) -> str:
    """Keep markdown citations but remove blank wrapper around them."""
    return text.strip()


def _extract_sources(payload: dict[str, Any], answer: str) -> list[WebSource]:
    found: list[WebSource] = []
    _walk_sources(payload, found)
    for title, url in _MARKDOWN_LINK_RE.findall(answer):
        found.append(WebSource(title=title.strip(), url=url))
    return _unique_sources(found)


def _walk_sources(value: Any, found: list[WebSource]) -> None:
    if isinstance(value, dict):
        item_type = str(value.get("type") or "")
        if item_type in {
            "web_search_call",
            "web_search_result",
            "web_search_tool_result",
        }:
            url = str(
                value.get("url")
                or value.get("display_url")
                or (value.get("web_search_result") or {}).get("url")
                or ""
            )
            title = str(
                value.get("title")
                or (value.get("web_search_result") or {}).get("title")
                or ""
            )
            snippet = str(
                value.get("snippet")
                or value.get("description")
                or (value.get("web_search_result") or {}).get("snippet")
                or ""
            )
            if url:
                found.append(WebSource(title=title or url, url=url, snippet=snippet))
        for child in value.values():
            _walk_sources(child, found)
    elif isinstance(value, list):
        for child in value:
            _walk_sources(child, found)


def _is_supported_content_type(content_type: str) -> bool:
    return any(
        marker in content_type
        for marker in (
            "text/html",
            "text/plain",
            "text/markdown",
            "application/xhtml+xml",
            "application/xml",
            "application/json",
        )
    )


def _extract_page(body: bytes, content_type: str) -> tuple[str, str]:
    text = body.decode("utf-8", errors="replace")
    title = ""
    if "html" in content_type or "<html" in text.lower():
        title_match = _TITLE_RE.search(text)
        if title_match:
            title = html.unescape(_strip_tags(title_match.group(1))).strip()
        text = _strip_tags(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text[:100_000], title


def _strip_tags(text: str) -> str:
    text = re.sub(
        r"<(script|style|nav|header|footer)[^>]*>.*?</\1>",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<(br|/p|/div|/li|/h[1-6])[^>]*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text)


def _is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _assert_public_ip(value: str) -> None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise WebPageReadError("目标主机地址无效") from exc
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise WebPageReadError("拒绝访问内网或本地地址")
