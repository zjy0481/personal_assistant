"""V3 orchestration for report Q&A with optional web search and page reads."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from assistant.config import Settings
from assistant.models import Report
from assistant.web_search import (
    DeepSeekWebSearchAdapter,
    WebPageReadError,
    WebPageReader,
    WebSearchAdapter,
    WebSource,
    detect_web_mode,
    extract_urls,
)

_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_SEARCH_KEYWORDS = (
    "今天",
    "现在",
    "最新",
    "实时",
    "新闻",
    "消息",
    "发布",
    "价格",
    "股价",
    "汇率",
    "更新",
    "进展",
    "发生了什么",
    "什么情况",
)


class WebDisabledError(RuntimeError):
    """Raised when web Q&A is disabled by configuration."""


@dataclass(frozen=True)
class WebAnswer:
    """One complete result from the web Q&A orchestration module."""

    answer: str
    citations: list[WebSource] = field(default_factory=list)
    used_web: bool = False
    status: str = "offline"
    message: str = ""
    stages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WebStreamEvent:
    """One SSE event emitted while a web answer is being produced."""

    event: str
    data: dict[str, Any]


class _DailyUsage:
    def __init__(self, limit: int, now: Any | None = None) -> None:
        self.limit = limit
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._day = self._now().date()
        self._count = 0

    def acquire(self) -> bool:
        if self.limit <= 0:
            return True
        with self._lock:
            current = self._now()
            if current.date() != self._day:
                self._day = current.date()
                self._count = 0
            if self._count >= self.limit:
                return False
            self._count += 1
            return True


class WebQAService:
    """Coordinate offline LLM answers, server-side search and page reads."""

    def __init__(
        self,
        settings: Settings,
        *,
        llm_service: Any,
        search_adapter: WebSearchAdapter | None = None,
        page_reader: WebPageReader | None = None,
        store: Any | None = None,
        daily_usage: _DailyUsage | None = None,
    ) -> None:
        self.settings = settings
        self.llm_service = llm_service
        self.search_adapter = search_adapter or DeepSeekWebSearchAdapter(settings)
        self.page_reader = page_reader or WebPageReader(settings)
        self.store = store
        self.daily_usage = daily_usage or _DailyUsage(
            settings.web_daily_limit,
        )

    def answer_question(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]] | None = None,
        mode: str = "auto",
    ) -> WebAnswer:
        history = history or []
        mode = self._resolve_mode(question, mode)
        if not self.settings.web_search_enabled:
            answer = self.llm_service.answer_question(report, question, history)
            return WebAnswer(
                answer=answer,
                citations=_extract_sources(answer),
                used_web=False,
                status="disabled",
                message="联网功能已关闭，本次回答仅基于日报信息。",
                stages=["offline"],
            )

        urls = extract_urls(question)
        if mode == "offline":
            answer = self.llm_service.answer_question(report, question, history)
            return WebAnswer(
                answer=answer,
                citations=_extract_sources(answer),
                used_web=False,
                status="offline",
                stages=["offline"],
            )

        if urls:
            return self._answer_with_pages(
                report,
                question,
                history,
                urls,
            )

        if mode == "force" or self._needs_search(question):
            return self._answer_with_search(report, question, history)

        answer = self.llm_service.answer_question(report, question, history)
        return WebAnswer(
            answer=answer,
            citations=_extract_sources(answer),
            used_web=False,
            status="offline",
            stages=["offline"],
        )

    def answer_question_events(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]] | None = None,
        mode: str = "auto",
    ) -> Iterator[WebStreamEvent]:
        """Yield status/delta/result events for a streaming chat response."""
        history = history or []
        mode = self._resolve_mode(question, mode)
        yield WebStreamEvent("status", {"stage": "starting"})
        if not self.settings.web_search_enabled:
            yield from self._offline_events(
                report,
                question,
                history,
                status="disabled",
                message="联网功能已关闭，本次回答仅基于日报信息。",
            )
            return
        if mode == "offline":
            yield from self._offline_events(
                report,
                question,
                history,
                status="offline",
            )
            return

        urls = extract_urls(question)
        if urls:
            yield from self._page_events(report, question, history, urls)
            return
        if mode == "force" or self._needs_search(question):
            yield from self._search_events(report, question, history)
            return
        yield from self._offline_events(
            report,
            question,
            history,
            status="offline",
        )

    def _offline_events(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]],
        *,
        status: str,
        message: str = "",
    ) -> Iterator[WebStreamEvent]:
        answer = self.llm_service.answer_question(
            report,
            question,
            history,
        )
        result = WebAnswer(
            answer=answer,
            citations=_extract_sources(answer),
            used_web=False,
            status=status,
            message=message,
            stages=["offline"],
        )
        yield WebStreamEvent("status", {"stage": "answering"})
        if answer:
            yield WebStreamEvent("delta", {"text": answer})
        yield WebStreamEvent(
            "result",
            _web_answer_to_dict(result),
        )

    def _page_events(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]],
        urls: list[str],
    ) -> Iterator[WebStreamEvent]:
        if not self._acquire_web_budget():
            yield from self._limited_events(report, question, history)
            return
        yield WebStreamEvent("status", {"stage": "reading"})
        pages: list[str] = []
        sources: list[WebSource] = []
        for url in urls[: self.settings.web_page_max_reads]:
            try:
                page = self._read_page_with_retry(url)
            except Exception as exc:
                result = self._failed_answer(
                    report,
                    question,
                    history,
                    f"网页读取失败：{exc}",
                    stages=["reading", "failed"],
                )
                yield from self._final_answer_events(result)
                return
            pages.append(
                f"来源：{page.url}\n标题：{page.title}\n正文：\n{page.text}"
            )
            sources.append(WebSource(page.title or page.url, page.url))
        yield WebStreamEvent("status", {"stage": "answering"})
        extra_context = "\n\n".join(pages)
        answer_parts: list[str] = []
        stream = getattr(self.llm_service, "answer_question_with_context_stream", None)
        if callable(stream):
            for delta in stream(
                report,
                question,
                history,
                extra_context=extra_context,
            ):
                answer_parts.append(delta)
                yield WebStreamEvent("delta", {"text": delta})
        else:
            answer = self.llm_service.answer_question_with_context(
                report,
                question,
                history,
                extra_context=extra_context,
            )
            answer_parts.append(answer)
            yield WebStreamEvent("delta", {"text": answer})
        result = WebAnswer(
            answer="".join(answer_parts),
            citations=_unique_sources(sources + _extract_sources("".join(answer_parts))),
            used_web=True,
            status="ok",
            stages=["reading", "answering"],
        )
        yield WebStreamEvent("result", _web_answer_to_dict(result))

    def _search_events(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]],
    ) -> Iterator[WebStreamEvent]:
        if not self._acquire_web_budget():
            yield from self._limited_events(report, question, history)
            return
        yield WebStreamEvent("status", {"stage": "searching"})
        context = self._build_context(report)
        answer_parts: list[str] = []
        sources: list[WebSource] = []
        stream = getattr(self.search_adapter, "search_stream", None)
        try:
            if callable(stream):
                for event, data in stream(
                    question,
                    context,
                    max_rounds=self.settings.web_search_max_rounds,
                ):
                    if event == "delta":
                        text = str(data.get("text") or "")
                        answer_parts.append(text)
                        yield WebStreamEvent("delta", {"text": text})
                    elif event == "result":
                        final_answer = str(data.get("answer") or "")
                        if not answer_parts:
                            answer_parts.append(final_answer)
                        for source in data.get("sources") or []:
                            if isinstance(source, dict):
                                sources.append(
                                    WebSource(
                                        str(source.get("title") or ""),
                                        str(source.get("url") or ""),
                                        str(source.get("snippet") or ""),
                                    )
                                )
            else:
                result = self._answer_with_search(
                    report,
                    question,
                    history,
                )
                if result.status != "ok":
                    yield from self._final_answer_events(result)
                    return
                answer_parts.append(result.answer)
                yield WebStreamEvent("delta", {"text": result.answer})
                sources = list(result.citations)
        except Exception as exc:
            result = self._failed_answer(
                report,
                question,
                history,
                f"联网检索失败：{exc}",
                stages=["searching", "failed"],
            )
            yield from self._final_answer_events(result)
            return
        answer = "".join(answer_parts)
        if not answer.strip():
            result = self._failed_answer(
                report,
                question,
                history,
                "联网检索没有返回可靠内容",
                stages=["searching", "failed"],
            )
            yield from self._final_answer_events(result)
            return
        result = WebAnswer(
            answer=answer,
            citations=_unique_sources(sources + _extract_sources(answer)),
            used_web=True,
            status="ok",
            stages=["searching", "answering"],
        )
        yield WebStreamEvent("status", {"stage": "answering"})
        yield WebStreamEvent("result", _web_answer_to_dict(result))

    def _limited_events(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]],
    ) -> Iterator[WebStreamEvent]:
        yield from self._final_answer_events(
            self._limited_answer(report, question, history)
        )

    def _final_answer_events(self, result: WebAnswer) -> Iterator[WebStreamEvent]:
        for stage in result.stages:
            yield WebStreamEvent("status", {"stage": stage})
        if result.answer:
            yield WebStreamEvent("delta", {"text": result.answer})
        yield WebStreamEvent("result", _web_answer_to_dict(result))

    def _answer_with_pages(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]],
        urls: list[str],
    ) -> WebAnswer:
        if not self._acquire_web_budget():
            return self._limited_answer(report, question, history)
        pages: list[str] = []
        sources: list[WebSource] = []
        for url in urls[: self.settings.web_page_max_reads]:
            try:
                page = self._read_page_with_retry(url)
            except (WebPageReadError, Exception) as exc:
                return self._failed_answer(
                    report,
                    question,
                    history,
                    f"网页读取失败：{exc}",
                    stages=["reading", "failed"],
                )
            pages.append(
                f"来源：{page.url}\n标题：{page.title}\n正文：\n{page.text}"
            )
            sources.append(WebSource(page.title or page.url, page.url))
        extra_context = "\n\n".join(pages)
        answer = self.llm_service.answer_question_with_context(
            report,
            question,
            history,
            extra_context=extra_context,
        )
        return WebAnswer(
            answer=answer,
            citations=_unique_sources(sources + _extract_sources(answer)),
            used_web=True,
            status="ok",
            stages=["reading", "answering"],
        )

    def _answer_with_search(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]],
    ) -> WebAnswer:
        if not self._acquire_web_budget():
            return self._limited_answer(report, question, history)
        context = self._build_context(report)
        try:
            result = self.search_adapter.search(
                question,
                context,
                max_rounds=self.settings.web_search_max_rounds,
            )
        except Exception as exc:
            return self._failed_answer(
                report,
                question,
                history,
                f"联网检索失败：{exc}",
                stages=["searching", "failed"],
            )
        if not result.answer.strip():
            return self._failed_answer(
                report,
                question,
                history,
                "联网检索没有返回可靠内容",
                stages=["searching", "failed"],
            )
        answer = result.answer.strip()
        citations = _unique_sources(
            list(result.sources) + _extract_sources(answer)
        )
        return WebAnswer(
            answer=answer,
            citations=citations,
            used_web=True,
            status="ok",
            stages=["searching", "answering"],
        )

    def _read_page_with_retry(self, url: str):
        try:
            return self.page_reader.read(url)
        except Exception:
            return self.page_reader.read(url)

    def _acquire_web_budget(self) -> bool:
        return self.daily_usage.acquire()

    def _limited_answer(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]],
    ) -> WebAnswer:
        answer = self.llm_service.answer_question(report, question, history)
        return WebAnswer(
            answer=f"已达到今日联网问答上限，以下仅基于日报信息：\n{answer}",
            citations=_extract_sources(answer),
            used_web=False,
            status="limited",
            message="今日联网问答已达到上限",
            stages=["limited", "offline"],
        )

    def _failed_answer(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]],
        message: str,
        *,
        stages: list[str],
    ) -> WebAnswer:
        answer = self.llm_service.answer_question(report, question, history)
        return WebAnswer(
            answer=f"{message}，以下仅基于日报信息：\n{answer}",
            citations=_extract_sources(answer),
            used_web=False,
            status="failed",
            message=message,
            stages=stages,
        )

    def _build_context(self, report: Report) -> str:
        lines = [
            f"地点：{report.location}",
            f"时区：{report.timezone}",
        ]
        for block in report.blocks:
            if not block.items:
                continue
            lines.append(f"## {block.title}")
            for item in block.items[:20]:
                summary = item.llm_summary or item.summary or "无摘要"
                lines.append(f"- {item.title}：{summary}")
                if item.url:
                    lines.append(f"  来源：{item.url}")
        if self.store is not None:
            try:
                favorites = self.store.list_favorites(limit=50)
                if favorites:
                    lines.append("## 收藏")
                    for favorite in favorites:
                        lines.append(f"- {favorite.title}：{favorite.url}")
                alerts = self.store.list_weather_alerts(
                    status="active",
                    limit=50,
                )
                if alerts:
                    lines.append("## 天气预警")
                    for alert in alerts:
                        lines.append(
                            f"- {alert.location} {alert.alert_type} "
                            f"{alert.level}：{alert.title} {alert.source_url}"
                        )
            except Exception:
                pass
        return "\n".join(lines) or "暂无日报内容。"

    @staticmethod
    def _resolve_mode(question: str, mode: str) -> str:
        if mode in ("force", "offline"):
            return mode
        return detect_web_mode(question)

    @staticmethod
    def _needs_search(question: str) -> bool:
        text = question.lower()
        return any(keyword in text for keyword in _SEARCH_KEYWORDS)


def _extract_sources(answer: str) -> list[WebSource]:
    return [
        WebSource(title=title.strip(), url=url)
        for title, url in _LINK_RE.findall(answer)
    ]


def _unique_sources(sources: list[WebSource]) -> list[WebSource]:
    result: list[WebSource] = []
    seen: set[str] = set()
    for source in sources:
        key = source.url.strip()
        if key in seen:
            continue
        seen.add(key)
        result.append(source)
    return result


def _web_answer_to_dict(result: WebAnswer) -> dict[str, Any]:
    return {
        "answer": result.answer,
        "citations": [
            {"title": source.title, "url": source.url}
            for source in result.citations
        ],
        "used_web": result.used_web,
        "status": result.status,
        "message": result.message,
        "stages": list(result.stages),
    }
