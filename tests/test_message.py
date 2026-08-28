from datetime import datetime
from zoneinfo import ZoneInfo

from assistant.message import render_push_markdown
from assistant.models import ContentBlock, ContentItem, Report


def _item(title: str, url: str, source: str, stars: int | None = None) -> ContentItem:
    return ContentItem(
        title=title,
        url=url,
        source=source,
        published_at=datetime(2026, 8, 29, 1, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        stars=stars,
    )


def _report() -> Report:
    return Report(
        title="上海日报 · 2026-08-29",
        generated_at=datetime(2026, 8, 29, 8, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        location="上海",
        timezone="Asia/Shanghai",
        blocks=[
            ContentBlock(
                kind="weather",
                title="上海天气",
                status="ok",
                details={
                    "current": {
                        "description": "晴",
                        "temperature": 25.0,
                        "humidity": 60,
                        "precipitation_probability": 10,
                        "air_quality_aqi": 42,
                    },
                    "days": [
                        {
                            "date": "2026-08-29",
                            "description": "晴",
                            "temp_min": 22.0,
                            "temp_max": 30.0,
                        }
                    ],
                },
            ),
            ContentBlock(
                kind="news",
                title="时事新闻",
                status="ok",
                items=[
                    _item("新闻一", "https://example.com/1", "人民网"),
                    _item("新闻二", "https://example.com/2", "人民网"),
                    _item("新闻三", "https://example.com/3", "人民网"),
                ],
            ),
            ContentBlock(
                kind="github",
                title="GitHub 热门",
                status="ok",
                items=[
                    _item("owner/repo", "https://github.com/owner/repo", "GitHub", 1234),
                    _item("owner/two", "https://github.com/owner/two", "GitHub", 999),
                ],
            ),
            ContentBlock(
                kind="ai",
                title="AI 领域要事",
                status="ok",
                items=[
                    _item("AI 动态", "https://example.com/ai", "OpenAI"),
                ],
            ),
        ],
    )


def test_push_markdown_includes_compact_sections_and_limits_items() -> None:
    rendered = render_push_markdown(_report(), max_items=2)

    assert "# 上海日报 · 2026-08-29" in rendered
    assert "当前：晴，25°C" in rendered
    assert "湿度：60%" in rendered
    assert "新闻一" in rendered
    assert "新闻二" in rendered
    assert "新闻三" not in rendered
    assert "owner/repo" in rendered
    assert "⭐1234" in rendered
    assert "AI 动态" in rendered
    assert "127.0.0.1" not in rendered


def test_push_markdown_fits_wecom_group_byte_limit() -> None:
    report = _report()
    report.blocks[1].items = [
        _item("超长标题" * 50, "https://example.com/long", "人民网")
        for _ in range(5)
    ]

    rendered = render_push_markdown(report, max_items=5, max_bytes=4096)

    assert len(rendered.encode("utf-8")) <= 4096
def test_push_markdown_marks_failed_section() -> None:
    report = Report(
        title="上海日报 · 2026-08-29",
        generated_at=datetime(2026, 8, 29, 8, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        location="上海",
        timezone="Asia/Shanghai",
        blocks=[
            ContentBlock(
                kind="news",
                title="时事新闻",
                status="failed",
                message="新闻源不可用",
            )
        ],
        degraded=True,
    )

    rendered = render_push_markdown(report, max_items=2)

    assert "时事新闻" in rendered
    assert "新闻源不可用" in rendered
    assert "部分数据源降级" in rendered
