from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from assistant.models import ContentBlock, ContentItem, Report
from assistant.storage import SnapshotStore


def _report() -> Report:
    return Report(
        title="上海日报 · 2026-08-29",
        generated_at=datetime(2026, 8, 29, 8, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        location="上海",
        timezone="Asia/Shanghai",
        blocks=[
            ContentBlock(
                kind="github",
                title="GitHub 热门",
                items=[
                    ContentItem(
                        title="openai/evals",
                        url="https://github.com/openai/evals",
                        source="GitHub Trending",
                        llm_summary="评测工具",
                        summary_status="ok",
                    )
                ],
            )
        ],
    )


def test_report_save_syncs_normalized_content_item(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "v2.db")
    report = _report()

    store.save(report)

    items = store.load_content_items()
    assert len(items) == 1
    assert items[0].stable_id == items[0].item_id
    assert items[0].llm_summary == "评测工具"
    assert items[0].summary_status == "ok"


def test_chat_history_is_persisted_and_can_be_cleaned(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "v2.db")

    store.save_chat_message("session-1", "user", "你好")
    store.save_chat_message("session-1", "assistant", "你好，有什么可以帮你？")

    history = store.load_chat_history("session-1")
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert store.delete_expired_chat_messages(days=7) == 0