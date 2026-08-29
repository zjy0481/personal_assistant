"""Generate one daily report snapshot without starting the web server.

Run from the project root:

    uv run python tests/manual_generate_report.py
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from assistant.config import load_settings
from assistant.report import ReportBuilder
from assistant.storage import SnapshotStore
from assistant.sources.ai import AINewsSource
from assistant.sources.github import GitHubTrendingSource
from assistant.sources.news import NewsSource
from assistant.sources.weather import OpenMeteoWeatherSource


def main() -> None:
    settings = load_settings()
    db_path = Path("data/assistant.db")

    builder = ReportBuilder(
        settings=settings,
        weather_source=OpenMeteoWeatherSource(),
        news_source=NewsSource(),
        github_source=GitHubTrendingSource(),
        ai_source=AINewsSource(),
    )

    report = builder.build(
        now=datetime.now(ZoneInfo(settings.timezone))
    )
    report_id = SnapshotStore(db_path).save(report)

    print(f"快照已保存：id={report_id}")
    print(f"标题：{report.title}")
    print(f"内容块：{len(report.blocks)} 个")
    print(f"存在降级：{report.degraded}")
    print(f"数据库：{db_path.resolve()}")
    print("启动服务后访问 http://127.0.0.1:8000/ 即可查看。")


if __name__ == "__main__":
    main()