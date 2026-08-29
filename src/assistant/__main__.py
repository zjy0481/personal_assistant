"""Run the web application or the daily report pipeline."""

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
        choices=["web", "daily"],
        help="启动网页服务或生成并推送日报",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新生成并覆盖当日日报快照",
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

    import uvicorn
    from assistant.main import app

    uvicorn.run(app, host="127.0.0.1", port=8000)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())