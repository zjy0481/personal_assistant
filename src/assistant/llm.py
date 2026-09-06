"""LLM client, rate limiting and report summarization/QA services."""

import logging
import json

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from assistant.config import Settings
from assistant.models import ContentItem, Report

logger = logging.getLogger(__name__)

SUMMARIZABLE_BLOCKS = {"news", "ai", "github"}
SUMMARY_CONCURRENCY = 3


class LLMError(RuntimeError):
    """Raised when an LLM request cannot be completed."""


class LLMNotConfiguredError(LLMError):
    """Raised when an LLM provider is not configured."""


class LLMRateLimitError(LLMError):
    """Raised when the configured rate limit is exceeded."""


class LLMCircuitOpenError(LLMError):
    """Raised while the circuit breaker is open."""


class LLMClient:
    """Thin LLM provider boundary."""

    def chat(self, messages: list[dict[str, str]]) -> str:
        raise NotImplementedError

    def stream_chat(self, messages: list[dict[str, str]]):
        yield self.chat(messages)


class DeepSeekLLMClient(LLMClient):
    """OpenAI-compatible DeepSeek chat completion client."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        api_key: str = "",
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-flash",
        timeout_seconds: int = 30,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key or (settings.llm_api_key if settings else "")
        self.base_url = base_url or (
            settings.llm_base_url if settings else "https://api.deepseek.com"
        )
        self.model = model or (settings.llm_model if settings else "deepseek-v4-flash")
        self.timeout_seconds = timeout_seconds or (
            settings.llm_timeout_seconds if settings else 30
        )
        self.client = client or httpx.Client(
            timeout=self.timeout_seconds,
            follow_redirects=True,
        )

    def chat(self, messages: list[dict[str, str]]) -> str:
        if not self.api_key:
            raise LLMNotConfiguredError("DeepSeek API Key 未配置")
        try:
            response = self.client.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 700,
                },
            )
            response.raise_for_status()
            payload = response.json()
            choices = payload.get("choices") or []
            if not choices:
                raise LLMError("DeepSeek 返回内容为空")
            content = choices[0].get("message", {}).get("content", "")
            if not content.strip():
                raise LLMError("DeepSeek 返回内容为空")
            return content.strip()
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(f"DeepSeek 请求失败: {exc}") from exc

    def stream_chat(self, messages: list[dict[str, str]]):
        if not self.api_key:
            raise LLMNotConfiguredError("DeepSeek API Key 未配置")
        try:
            with self.client.stream(
                "POST",
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 700,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    choice = (data.get("choices") or [{}])[0]
                    delta = (choice.get("delta") or {}).get("content") or ""
                    if delta:
                        yield delta
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(f"DeepSeek 流式请求失败: {exc}") from exc


class MockLLMClient(LLMClient):
    """Deterministic client used for offline tests and local no-key mode."""

    def __init__(self, prefix: str = "测试摘要") -> None:
        self.prefix = prefix

    def chat(self, messages: list[dict[str, str]]) -> str:
        last = messages[-1].get("content", "") if messages else ""
        title = ""
        for line in last.splitlines():
            if line.startswith("标题："):
                title = line.removeprefix("标题：").strip()
                break
        if title:
            return f"{self.prefix}：{title}"
        return f"{self.prefix}：请结合日报内容回答。"


class LLMRateLimiter:
    """Thread-safe daily/minute counter and simple circuit breaker."""

    def __init__(
        self,
        daily_limit: int = 300,
        minute_limit: int = 10,
        failure_threshold: int = 3,
        breaker_seconds: int = 60,
        now: datetime | None = None,
    ) -> None:
        self.daily_limit = daily_limit
        self.minute_limit = minute_limit
        self.failure_threshold = failure_threshold
        self.breaker_seconds = breaker_seconds
        self._now = now or datetime.now(timezone.utc)
        self._lock = threading.Lock()
        self._day = self._now.date()
        self._day_count = 0
        self._minute = self._now.replace(second=0, microsecond=0)
        self._minute_count = 0
        self._failures = 0
        self._circuit_open_until: datetime | None = None

    def check(self) -> None:
        with self._lock:
            current = datetime.now(timezone.utc)
            if self._circuit_open_until and current < self._circuit_open_until:
                raise LLMCircuitOpenError("LLM 熔断中，请稍后重试")
            self._rollover(current)
            if self._day_count >= self.daily_limit:
                raise LLMRateLimitError("已达到每日 LLM 调用上限")
            if self._minute_count >= self.minute_limit:
                raise LLMRateLimitError("已达到每分钟 LLM 调用上限")

    def record_success(self) -> None:
        with self._lock:
            current = datetime.now(timezone.utc)
            self._rollover(current)
            self._day_count += 1
            self._minute_count += 1
            self._failures = 0
            self._circuit_open_until = None

    def record_failure(self) -> None:
        with self._lock:
            current = datetime.now(timezone.utc)
            self._rollover(current)
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._circuit_open_until = current + timedelta(
                    seconds=self.breaker_seconds
                )

    def _rollover(self, current: datetime) -> None:
        if current.date() != self._day:
            self._day = current.date()
            self._day_count = 0
        bucket = current.replace(second=0, microsecond=0)
        if bucket != self._minute:
            self._minute = bucket
            self._minute_count = 0


class LLMService:
    """Shared summarization and report QA service."""

    def __init__(
        self,
        settings: Settings,
        client: LLMClient | None = None,
        limiter: LLMRateLimiter | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or DeepSeekLLMClient(settings)
        self.limiter = limiter or LLMRateLimiter(
            daily_limit=settings.llm_daily_limit,
            minute_limit=settings.llm_minute_limit,
            failure_threshold=settings.llm_failure_threshold,
            breaker_seconds=settings.llm_circuit_breaker_seconds,
        )

    @property
    def configured(self) -> bool:
        if isinstance(self.client, DeepSeekLLMClient):
            return bool(self.client.api_key)
        return True

    def summarize_report(self, report: Report) -> Report:
        if not self.settings.llm_summary_enabled:
            for block in report.blocks:
                if block.kind in SUMMARIZABLE_BLOCKS:
                    for item in block.items:
                        if not item.summary_status:
                            item.summary_status = "disabled"
            return report

        pending: list[ContentItem] = []
        for block in report.blocks:
            if block.kind not in SUMMARIZABLE_BLOCKS:
                continue
            for item in block.items:
                if item.summary_status:
                    continue
                if len(pending) >= self.settings.llm_max_items:
                    break
                pending.append(item)

        if not pending:
            return report

        workers = max(1, min(SUMMARY_CONCURRENCY, len(pending)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(self.summarize_item, pending))
        for item, result in zip(pending, results):
            if result[1] == "failed":
                result = self.summarize_item(item)
            item.llm_summary, item.summary_status, item.summary_model = result
        return report

    def summarize_item(self, item: ContentItem) -> tuple[str, str, str]:
        if not self.configured:
            return "", "not_configured", ""
        system = (
            "你是一名严谨的中文日报摘要助手。请根据给定内容，用1-3句简体中文"
            "概括核心信息。必须始终使用简体中文输出，即使标题或原文是英文，也要转述为中文。"
            "只使用提供的标题、摘要和来源信息，不得补充原文没有的事实。"
            "不要输出链接、markdown 标题、英文原文或额外说明。"
        )
        user = (
            f"标题：{item.title}\n"
            f"原文摘要：{item.summary or '无'}\n"
            f"来源：{item.source}\n"
            f"请只输出简体中文简介，不要输出英文。"
        )
        try:
            self.limiter.check()
            result = self._chat(system, user)
            self.limiter.record_success()
            return result, "ok", self.settings.llm_model
        except LLMRateLimitError as exc:
            logger.warning("LLM 摘要被限流（%s）：%s", item.title, exc)
            return "", "rate_limited", self.settings.llm_model
        except (LLMCircuitOpenError, LLMError) as exc:
            self.limiter.record_failure()
            logger.warning("LLM 摘要失败（%s）：%s", item.title, exc)
            return "", "failed", self.settings.llm_model

    def answer_question(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]] | None = None,
        extra_context: str = "",
    ) -> str:
        if not self.configured:
            raise LLMNotConfiguredError("LLM API Key 未配置，无法进行网页问答")
        history = history or []
        context = self._build_report_context(report)
        system = (
            "你是个人日报助手。请始终使用简体中文回答用户问题，"
            "即使问题或原文是英文也要转述为中文。"
            "只能基于提供的日报上下文作答，回答事实时引用来源，"
            "格式为 [标题](URL)。回答可以使用 Markdown 让内容更易读。"
            "若上下文不足，请明确说明无法从日报判断，不要编造。"
        )
        user = f"日报上下文：\n{context}\n"
        if extra_context:
            user += f"\n补充材料：\n{extra_context}\n"
        user += f"\n用户问题：{question}"
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        messages.extend(history[-8:])
        messages.append({"role": "user", "content": user})
        try:
            self.limiter.check()
            answer = self._chat_raw(messages)
            self.limiter.record_success()
            return answer
        except (LLMRateLimitError, LLMCircuitOpenError, LLMError) as exc:
            self.limiter.record_failure()
            raise LLMError(f"问答失败: {exc}") from exc

    def answer_question_with_context(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]] | None = None,
        extra_context: str = "",
    ) -> str:
        return self.answer_question(
            report,
            question,
            history,
            extra_context=extra_context,
        )

    def answer_question_with_context_stream(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]] | None = None,
        extra_context: str = "",
    ):
        if not self.configured:
            raise LLMNotConfiguredError("LLM API Key 未配置，无法进行网页问答")
        history = history or []
        context = self._build_report_context(report)
        system = (
            "你是个人日报助手。请始终使用简体中文回答用户问题，"
            "即使问题或原文是英文也要转述为中文。"
            "只能基于提供的日报上下文和补充材料作答，回答事实时引用来源，"
            "格式为 [标题](URL)。若无法确认，请明确说明。"
        )
        user = f"日报上下文：\n{context}\n"
        if extra_context:
            user += f"\n补充材料：\n{extra_context}\n"
        user += f"\n用户问题：{question}"
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        messages.extend(history[-10:])
        messages.append({"role": "user", "content": user})
        try:
            self.limiter.check()
            for delta in self._stream_raw(messages):
                if delta:
                    yield delta
            self.limiter.record_success()
        except (LLMRateLimitError, LLMCircuitOpenError, LLMError) as exc:
            self.limiter.record_failure()
            raise LLMError(f"问答失败: {exc}") from exc

    def _chat(self, system: str, user: str) -> str:
        return self._chat_raw(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )

    def _chat_raw(self, messages: list[dict[str, str]]) -> str:
        if not self.client:
            raise LLMNotConfiguredError("LLM Client 未配置")
        return self.client.chat(messages)

    def _stream_raw(self, messages: list[dict[str, str]]):
        if not self.client:
            raise LLMNotConfiguredError("LLM Client 未配置")
        stream = getattr(self.client, "stream_chat", None)
        if callable(stream):
            yield from stream(messages)
        else:
            yield self.client.chat(messages)

    @staticmethod
    def _build_report_context(report: Report) -> str:
        lines: list[str] = []
        for block in report.blocks:
            if not block.items:
                continue
            lines.append(f"## {block.title}")
            for item in block.items[:20]:
                summary = item.llm_summary or item.summary or "无摘要"
                lines.append(f"- {item.title}：{summary}")
                if item.url:
                    lines.append(f"  来源：{item.url}")
        if not lines:
            return "暂无日报内容。"
        return "\n".join(lines)


def create_llm_service(settings: Settings) -> LLMService:
    """Create a production LLM service from the configured settings."""
    return LLMService(settings)
