"""Manually verify PushPlus and WeCom group webhook channels.

Run from the project root:

    uv run python tests/verify_push.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx

ENV_FILE = Path(".env")
PUSHPLUS_URL = "https://www.pushplus.plus/send"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PUSHPLUS_URL = "https://www.pushplus.plus/send"


def load_env_value(key: str) -> str:
    """Read a value from the project ``.env`` without exposing secrets."""

    if not ENV_FILE.is_file():
        return ""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, _, value = stripped.partition("=")
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


def verify_pushplus(token: str, client: httpx.Client) -> bool:
    if not token:
        print("[PushPlus] 未配置 ASSISTANT_PUSHPLUS_TOKEN，跳过。")
        return False

    payload = {
        "token": token,
        "title": "日报推送验证",
        "content": "**验证消息**：如果你看到这条消息，说明 PushPlus 推送链路可用。",
        "template": "markdown",
        "channel": "wechat",
    }
    try:
        response = client.post(PUSHPLUS_URL, json=payload)
        response.raise_for_status()
        data = parse_json(response)
    except Exception as exc:
        print(f"[PushPlus] 请求失败：{exc}")
        return False

    code = data.get("code")
    if code == 200:
        short_code = data.get("data", "")
        print(f"[PushPlus] 请求已接受，shortCode={short_code}")
        print("[PushPlus] 请到微信中确认是否收到验证消息。")
        return True

    print(f"[PushPlus] 接口返回 code={code}, msg={data.get('msg', '')}")
    if code == 905:
        print("[PushPlus] 未实名认证，请先在 PushPlus 完成微信实名认证。")
    elif code == 903:
        print("[PushPlus] token 无效，请重新复制用户 token。")
    elif code == 900:
        print("[PushPlus] 账号当前受限，请稍后重试。")
    return False


def verify_wecom_group(webhook: str, client: httpx.Client) -> bool:
    if not webhook:
        print("[企业微信群机器人] 未配置 ASSISTANT_WECOM_GROUP_WEBHOOK，跳过。")
        return False
    if "/cgi-bin/webhook/send" not in webhook:
        print("[企业微信群机器人] Webhook URL 格式不正确，请检查。")
        return False

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": "**日报推送验证**\n如果你看到这条消息，说明企业微信群机器人推送链路可用。",
        },
    }
    try:
        response = client.post(webhook, json=payload, timeout=10.0)
        response.raise_for_status()
        data = parse_json(response)
    except Exception as exc:
        print(f"[企业微信群机器人] 请求失败：{exc}")
        return False

    errcode = data.get("errcode")
    if errcode == 0:
        print("[企业微信群机器人] 推送成功，请到群聊中确认。")
        return True

    print(
        f"[企业微信群机器人] 返回 errcode={errcode}, "
        f"errmsg={data.get('errmsg', '')}"
    )
    return False


def parse_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError(f"响应不是有效 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("响应 JSON 不是对象")
    return payload


def main() -> int:
    token = load_env_value("ASSISTANT_PUSHPLUS_TOKEN")
    webhook = load_env_value("ASSISTANT_WECOM_GROUP_WEBHOOK")

    if not token and not webhook:
        print("未找到任何推送凭证，请在项目根目录 .env 中配置：")
        print("  ASSISTANT_PUSHPLUS_TOKEN=<来自 PushPlus 的用户 token>")
        print("  ASSISTANT_WECOM_GROUP_WEBHOOK=<企业微信群机器人 Webhook URL>")
        return 2

    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        token_ok = verify_pushplus(token, client)
        webhook_ok = verify_wecom_group(webhook, client)

    results = []
    if token:
        results.append(("PushPlus", token_ok))
    if webhook:
        results.append(("企业微信群机器人", webhook_ok))
    for name, ok in results:
        print(f"{name}: {'成功' if ok else '失败'}")
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
