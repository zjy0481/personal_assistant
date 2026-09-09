"""Diagnostic tests for V3 page-read 403 handling.

These tests intentionally document the current failure path without changing
business code. They let us verify that an anti-bot 403 page surfaces as
``httpx.HTTPStatusError`` and then degrades the web answer to offline.
"""

from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from assistant.config import Settings
from assistant.models import Report
from assistant.web_qa import WebQAService
from assistant.web_search import WebPageReader


def _settings() -> Settings:
    return Settings(
        location="上海",
        timezone="Asia/Shanghai",
        llm_api_key="test-deepseek-key",
        web_search_model="deepseek-v4-flash",
        web_search_enabled=True,
    )


def _report() -> Report:
    return Report(
        title="测试日报",
        generated_at=datetime.now(timezone.utc),
        location="上海",
        timezone="Asia/Shanghai",
        blocks=[],
    )


def _forbidden_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"content-type": "text/html; charset=utf-8"},
            text=(
                "<html><head><title>百度安全验证</title></head>"
                "<body>请开启 JavaScript 后重试</body></html>"
            ),
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


class _FakeLLM:
    def answer_question(
        self,
        report: Report,
        question: str,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        return "离线降级回答"


def test_page_reader_surfaces_403_for_anti_bot_page() -> None:
    reader = WebPageReader(
        _settings(),
        client=_forbidden_client(),
        resolver=lambda host: ["8.8.8.8"],
    )

    with pytest.raises(httpx.HTTPStatusError):
        reader.read("https://baike.baidu.com/item/test/1")


def test_web_qa_degrades_to_failed_after_403() -> None:
    service = WebQAService(
        _settings(),
        llm_service=_FakeLLM(),
        page_reader=WebPageReader(
            _settings(),
            client=_forbidden_client(),
            resolver=lambda host: ["8.8.8.8"],
        ),
    )

    events = list(
        service.answer_question_events(
            _report(),
            "请读取 https://baike.baidu.com/item/test/1 并简述",
            mode="force",
        )
    )

    result = next(event.data for event in events if event.event == "result")
    assert isinstance(result, dict)
    assert result["status"] == "failed"
    assert "网页读取失败" in result["answer"]
    assert "403 Forbidden" in result["message"]
