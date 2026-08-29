"""Daily report push adapters and ordered channel fallback chain."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from assistant.config import Settings
from assistant.message import render_push_markdown
from assistant.models import Report

logger = logging.getLogger(__name__)
DEFAULT_WEB_URL = "http://127.0.0.1:8000/"
PUSHPLUS_URL = "https://www.pushplus.plus/send"


@dataclass
class PushResult:
    """Outcome of one report push attempt."""

    success: bool
    mode: str
    message: str = ""
    errcode: int | None = None
    fallback: bool = False
    channel: str = ""
    short_code: str = ""
    retryable: bool = True


class PushConfigurationError(ValueError):
    """Raised when required push credentials or configuration are missing."""


class PushError(RuntimeError):
    """Raised when a push provider rejects or cannot process a request."""


class PushAdapter:
    """Public push boundary used by the scheduler and integrations."""

    def send_report(self, report: Report) -> PushResult:
        raise NotImplementedError


class MockPushAdapter(PushAdapter):
    """Deterministic adapter used for local validation."""

    def __init__(self, result: PushResult | None = None) -> None:
        self.result = result or PushResult(
            success=True,
            mode="mock",
            channel="mock",
            message="mock 推送完成",
        )

    def send_report(self, report: Report) -> PushResult:
        return self.result


class PushPlusPushAdapter(PushAdapter):
    """Send a report through PushPlus WeChat service account."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.Client | None = None,
        token: str | None = None,
        max_items: int | None = None,
        url: str | None = None,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=10.0,
            follow_redirects=True,
        )
        self.token = token or (settings.pushplus_token if settings else "")
        self.max_items = (
            max_items
            if max_items is not None
            else (settings.push_max_items if settings else 5)
        )
        self.url = url or PUSHPLUS_URL

    def send_report(self, report: Report) -> PushResult:
        if not self.token:
            return PushResult(
                success=False,
                mode="failed",
                channel="pushplus",
                message="PushPlus 配置缺失：pushplus_token",
                retryable=False,
            )
        try:
            response = self.client.post(
                self.url,
                json={
                    "token": self.token,
                    "title": report.title,
                    "content": render_push_markdown(report, self.max_items),
                    "template": "markdown",
                    "channel": "wechat",
                },
            )
            response.raise_for_status()
            body = self._parse_response(response)
        except Exception as exc:
            logger.error("PushPlus 推送失败: %s", exc)
            return PushResult(
                success=False,
                mode="failed",
                channel="pushplus",
                message=f"PushPlus 请求失败: {exc}",
            )

        code = int(body.get("code", -1))
        if code == 200:
            return PushResult(
                success=True,
                mode="pushplus",
                channel="pushplus",
                message="PushPlus 请求已接受，请等待微信送达",
                errcode=code,
                short_code=str(body.get("data", "")),
            )

        message = f"PushPlus 返回 code={code}, msg={body.get('msg', '')}"
        if code == 905:
            message += "；请先完成 PushPlus 实名认证"
        elif code == 903:
            message += "；token 无效，请重新获取"
        elif code == 900:
            message += "；账号受限，请稍后重试"
        logger.error(message)
        return PushResult(
            success=False,
            mode="failed",
            channel="pushplus",
            message=message,
            errcode=code,
            retryable=False,
        )

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception as exc:
            raise PushError(f"PushPlus 响应解析失败: {exc}") from exc
        if not isinstance(payload, dict):
            raise PushError("PushPlus 响应不是 JSON 对象")
        return payload


class WeComGroupWebhookPushAdapter(PushAdapter):
    """Send a report through an Enterprise WeChat group robot webhook."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.Client | None = None,
        webhook: str | None = None,
        max_items: int | None = None,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=10.0,
            follow_redirects=True,
        )
        self.webhook = webhook or (
            settings.wecom_group_webhook if settings else ""
        )
        self.max_items = (
            max_items
            if max_items is not None
            else (settings.push_max_items if settings else 5)
        )

    def send_report(self, report: Report) -> PushResult:
        if not self.webhook:
            return PushResult(
                success=False,
                mode="failed",
                channel="wecom_group",
                message="企业微信群机器人配置缺失：wecom_group_webhook",
                retryable=False,
            )
        if "/cgi-bin/webhook/send" not in self.webhook:
            return PushResult(
                success=False,
                mode="failed",
                channel="wecom_group",
                message="企业微信群机器人 Webhook URL 格式不正确",
                retryable=False,
            )
        try:
            response = self.client.post(
                self.webhook,
                json={
                    "msgtype": "markdown",
                    "markdown": {
                        "content": render_push_markdown(report, self.max_items, max_bytes=4096),
                    },
                },
            )
            response.raise_for_status()
            body = self._parse_response(response)
        except Exception as exc:
            logger.error("企业微信群机器人推送失败: %s", exc)
            return PushResult(
                success=False,
                mode="failed",
                channel="wecom_group",
                message=f"企业微信群机器人请求失败: {exc}",
            )

        errcode = int(body.get("errcode", -1))
        if errcode == 0:
            return PushResult(
                success=True,
                mode="wecom_group",
                channel="wecom_group",
                message="企业微信群机器人推送成功",
                errcode=errcode,
            )
        message = (
            f"企业微信群机器人返回 errcode={errcode}, "
            f"errmsg={body.get('errmsg', '')}"
        )
        logger.error(message)
        return PushResult(
            success=False,
            mode="failed",
            channel="wecom_group",
            message=message,
            errcode=errcode,
            retryable=False,
        )

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception as exc:
            raise PushError(f"企业微信响应解析失败: {exc}") from exc
        if not isinstance(payload, dict):
            raise PushError("企业微信响应不是 JSON 对象")
        return payload


class WeComPushAdapter(PushAdapter):
    """Legacy Enterprise WeChat self-built application adapter."""

    TOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    SEND_URL = "https://qyapi.weixin.qq.com/cgi-bin/message/send"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.Client | None = None,
        corpid: str | None = None,
        agentid: str | None = None,
        secret: str | None = None,
        userid: str | None = None,
        web_url: str | None = None,
        failure_notifier: Callable[[str], None] | None = None,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=10.0,
            follow_redirects=True,
        )
        self.settings = settings
        self.corpid = corpid or (settings.wecom_corpid if settings else "")
        self.agentid = agentid or (settings.wecom_agentid if settings else "")
        self.secret = secret or (settings.wecom_secret if settings else "")
        self.userid = userid or (settings.wecom_userid if settings else "")
        self.web_url = (
            web_url
            or (settings.web_url if settings else "")
            or DEFAULT_WEB_URL
        )
        self.failure_notifier = failure_notifier or self._log_failure
        self._access_token = ""
        self._token_expires_at = datetime.min.replace(tzinfo=timezone.utc)

    def send_report(self, report: Report) -> PushResult:
        try:
            self._ensure_configured()
            token = self._get_access_token()
            try:
                errcode, errmsg = self._send_textcard(token, report)
                if errcode != 0:
                    raise PushError(f"企业微信返回错误：code={errcode}, msg={errmsg}")
            except PushError as exc:
                logger.warning("textcard 推送失败，尝试 text：%s", exc)
                errcode, errmsg = self._send_text(token, report)
                if errcode != 0:
                    raise PushError(
                        f"text 回退也失败：{errmsg or 'unknown error'}"
                    ) from exc
                return PushResult(
                    success=True,
                    mode="text",
                    channel="wechat_work",
                    message="已通过 text 回退发送",
                    errcode=errcode,
                    fallback=True,
                )

            return PushResult(
                success=True,
                mode="textcard",
                channel="wechat_work",
                message="日报卡片已发送",
                errcode=errcode,
            )
        except Exception as exc:
            message = f"企业微信日报发送失败: {exc}"
            logger.error(message)
            self.failure_notifier(message)
            return PushResult(
                success=False,
                mode="failed",
                channel="wechat_work",
                message=message,
            )

    def _ensure_configured(self) -> None:
        missing = []
        if not self.corpid:
            missing.append("corpid")
        if not self.agentid:
            missing.append("agentid")
        if not self.secret:
            missing.append("secret")
        if not self.userid:
            missing.append("userid")
        if missing:
            raise PushConfigurationError(
                f"企业微信配置缺失: {', '.join(missing)}"
            )

    def _get_access_token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        response = self.client.get(
            self.TOKEN_URL,
            params={"corpid": self.corpid, "corpsecret": self.secret},
        )
        payload = self._parse_response(response)
        errcode = payload.get("errcode")
        if errcode != 0:
            raise PushError(
                f"获取 access_token 失败：code={errcode}, msg={payload.get('errmsg')}"
            )
        self._access_token = payload.get("access_token", "")
        expires_in = int(payload.get("expires_in", 7200))
        self._token_expires_at = now + timedelta(seconds=expires_in)
        return self._access_token

    def _send_textcard(self, token: str, report: Report) -> tuple[int, str]:
        payload: dict[str, Any] = {
            "touser": self.userid,
            "msgtype": "textcard",
            "agentid": int(self.agentid),
            "textcard": {
                "title": report.title,
                "description": self._build_description(report),
                "url": self.web_url,
                "btntxt": "查看日报",
            },
            "safe": 0,
        }
        return self._send_payload(token, payload)

    def _send_text(self, token: str, report: Report) -> tuple[int, str]:
        payload: dict[str, Any] = {
            "touser": self.userid,
            "msgtype": "text",
            "agentid": int(self.agentid),
            "text": {"content": self._build_description(report)},
            "safe": 0,
        }
        return self._send_payload(token, payload)

    def _send_payload(
        self,
        token: str,
        payload: dict[str, Any],
    ) -> tuple[int, str]:
        try:
            response = self.client.post(
                self.SEND_URL,
                params={"access_token": token},
                json=payload,
            )
            body = self._parse_response(response)
        except Exception as exc:
            raise PushError(f"企业微信请求失败: {exc}") from exc
        return int(body.get("errcode", -1)), str(body.get("errmsg", ""))

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict[str, Any]:
        try:
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise PushError(f"企业微信响应解析失败: {exc}") from exc
        if not isinstance(payload, dict):
            raise PushError("企业微信响应不是 JSON 对象")
        return payload

    @staticmethod
    def _build_description(report: Report) -> str:
        lines = [
            report.title,
            f"地区：{report.location}",
        ]
        for block in report.blocks:
            if block.status == "failed":
                lines.append(f"· {block.title}：{block.message or '数据不可用'}")
            elif block.kind == "weather":
                current = block.details.get("current", {})
                if current.get("temperature") is not None:
                    lines.append(
                        f"· 当前 {current.get('description', '')}，"
                        f"{current.get('temperature')}°C"
                    )
                else:
                    lines.append(f"· {block.title}：可用")
            else:
                lines.append(f"· {block.title}：{len(block.items)} 条")
        text = "\n".join(lines)
        if len(text) > 500:
            return text[:500] + "…"
        return text

    def _log_failure(self, message: str) -> None:
        logger.error(message)


class PushChainAdapter(PushAdapter):
    """Try configured channels in order until one succeeds."""

    def __init__(
        self,
        adapters: Sequence[PushAdapter],
        *,
        failure_notifier: Callable[[str], None] | None = None,
    ) -> None:
        self.adapters = list(adapters)
        self.failure_notifier = failure_notifier or self._log_failure

    def send_report(self, report: Report) -> PushResult:
        failures: list[PushResult] = []
        for index, adapter in enumerate(self.adapters):
            try:
                result = adapter.send_report(report)
            except Exception as exc:
                logger.error("推送渠道异常: %s", exc)
                result = PushResult(
                    success=False,
                    mode="failed",
                    message=f"推送渠道异常: {exc}",
                )
            if result.success:
                result.fallback = index > 0
                return result
            failures.append(result)

        message = "所有推送渠道均失败: " + "; ".join(
            item.message or "未知错误" for item in failures
        )
        logger.error(message)
        self.failure_notifier(message)
        return PushResult(
            success=False,
            mode="failed",
            message=message,
            channel=failures[-1].channel if failures else "",
            errcode=failures[-1].errcode if failures else None,
            short_code=failures[-1].short_code if failures else "",
            retryable=failures[-1].retryable if failures else True,
        )

    def _log_failure(self, message: str) -> None:
        logger.error(message)


def create_push_adapter(
    settings: Settings,
    client: httpx.Client | None = None,
    failure_notifier: Callable[[str], None] | None = None,
) -> PushAdapter:
    """Create the ordered adapter chain; mock mode is available for tests."""

    if settings.push_mock or settings.wecom_mock:
        return MockPushAdapter()

    adapters: list[PushAdapter] = []
    for channel in settings.push_channels:
        if channel == "pushplus":
            adapters.append(PushPlusPushAdapter(settings=settings, client=client))
        elif channel == "wecom_group":
            adapters.append(
                WeComGroupWebhookPushAdapter(settings=settings, client=client)
            )
        elif channel == "wechat_work":
            adapters.append(
                WeComPushAdapter(
                    settings=settings,
                    client=client,
                    failure_notifier=lambda _message: None,
                )
            )
        else:
            raise PushConfigurationError(f"未知推送渠道: {channel}")

    if not adapters:
        raise PushConfigurationError("未配置任何推送渠道")
    return PushChainAdapter(adapters, failure_notifier=failure_notifier)