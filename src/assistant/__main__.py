"""Run the web application, daily report pipeline or warning monitor."""

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="assistant",
        description="Personal daily report assistant",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="web",
        choices=["web", "daily", "alerts", "wecom", "bot"],
        help="启动网页服务、日报、预警监测或企业微信智能机器人",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新生成并覆盖当日日报快照",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="预警监测只执行一次后退出",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="预警轮询间隔（秒），覆盖配置文件默认值",
    )
    args = parser.parse_args()

    if args.command == "daily":
        from assistant.daily import run_daily

        result = run_daily(force=args.force)
        print(f"推送结果：{'成功' if result.success else '失败'}")
        print(result.message)
        if result.channel:
            print(f"渠道：{result.channel}")
        if result.short_code:
            print(f"消息流水号：{result.short_code}")
        return 0 if result.success else 1

    if args.command == "alerts":
        from assistant.weather_alert_service import run_alert_monitor

        try:
            result = run_alert_monitor(once=args.once, interval_seconds=args.interval)
        except KeyboardInterrupt:
            print("极端天气预警监测已停止")
            return 0
        print(
            f"预警检查：{result.status}；"
            f"源={result.source or '-'}；"
            f"预警={result.alert_count}；推送={result.pushed_count}"
        )
        print(result.message or "完成")
        return 0 if result.status in ("ok", "paused", "disabled", "stopped") else 1

    if args.command in ("wecom", "bot"):
        from assistant.wecom_ai_service import run_wecom_bot

        return run_wecom_bot()

    from assistant.main import app

    uvicorn.run(app, host="127.0.0.1", port=8000)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
