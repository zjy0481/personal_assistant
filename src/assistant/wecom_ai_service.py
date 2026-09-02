"""Enterprise WeChat smart robot long-connection service for group Q&A."""

import json
import logging
import re
from pathlib import Path
import secrets
import time
from dataclasses import dataclass
from typing import Any

import websockets
from websockets.sync.client import connect as ws_connect

from assistant.config import Settings, load_settings
from assistant.llm import LLMError, LLMNotConfiguredError, create_llm_service
from assistant.storage import SnapshotStore

logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"@\S+")
_MAX_REPLY_CHARS = 18000


class WeComAIConfigError(RuntimeError):
    """Raised when the smart robot configuration is incomplete or invalid."""


class WeComAIConnectionError(RuntimeError):
    """Raised when the long connection cannot subscribe or stay connected."""


@dataclass(frozen=True)
class WeComInboundMessage:
    req_id: str
    msgid: str
    aibot_id: str
    chat_id: str
    chat_type: str
    from_userid: str
    msg_type: str
    content: str


def parse_message_payload(payload: dict[str, Any]) -> WeComInboundMessage | None:
    """Parse a long-connection message callback into a normalized message."""
    body = payload.get("body")
    if not isinstance(body, dict):
        return None
    headers = payload.get("headers")
    if not isinstance(headers, dict):
        headers = {}
    msg_type = body.get("msgtype", "")
    content = _extract_content(body)
    if not content:
        content = _extract_quote_text(body)
    from_info = body.get("from") or {}
    if not isinstance(from_info, dict):
        from_info = {}
    return WeComInboundMessage(
        req_id=str(headers.get("req_id") or secrets.token_urlsafe(8)),
        msgid=str(body.get("msgid") or ""),
        aibot_id=str(body.get("aibotid") or ""),
        chat_id=str(body.get("chatid") or ""),
        chat_type=str(body.get("chattype") or ""),
        from_userid=str(from_info.get("userid") or ""),
        msg_type=msg_type,
        content=content,
    )


def has_bot_mention(content: str, bot_name: str) -> bool:
    if "@" not in content:
        return False
    if not bot_name.strip():
        return bool(_MENTION_RE.search(content))
    return re.search(rf"@\s*{re.escape(bot_name.strip())}", content) is not None


def strip_bot_mention(content: str, bot_name: str) -> str:
    if bot_name.strip():
        content = re.sub(
            rf"@\s*{re.escape(bot_name.strip())}\s*",
            "",
            content,
            count=1,
        )
    else:
        content = re.sub(r"@\S+\s*", "", content, count=1)
    return content.strip()


class WeComAIBot:
    """Connect to the smart robot WebSocket and answer @ mentions."""

    def __init__(
        self,
        settings: Settings,
        *,
        store: SnapshotStore | None = None,
        llm_service: Any | None = None,
        connect_factory: Any = None,
        sleep: Any = time.sleep,
    ) -> None:
        self.settings = settings
        self.store = store or SnapshotStore(Path("data/assistant.db"))
        self.llm_service = llm_service or create_llm_service(settings)
        self._connect_factory = connect_factory or ws_connect
        self._sleep = sleep
        self._stop = False

    @property
    def enabled(self) -> bool:
        return self.settings.wecom_ai_active

    def validate(self) -> None:
        if not self.enabled:
            raise WeComAIConfigError("企业微信智能机器人未启用")
        if self.settings.wecom_ai_mode != "long_connection":
            raise WeComAIConfigError(
                "当前实现仅支持 long_connection；请设置 wecom_ai_mode=long_connection"
            )
        if not self.settings.wecom_ai_bot_id.strip() or not self.settings.wecom_ai_bot_secret.strip():
            raise WeComAIConfigError(
                "企业微信智能机器人缺少 BotID 或 Secret"
            )

    def run(self) -> None:
        if not self.enabled:
            logger.info("企业微信智能机器人未启用，服务退出")
            return
        self.validate()
        self.store.delete_expired_wecom_ai_messages(
            self.settings.wecom_ai_retention_days,
        )
        if not self.settings.wecom_ai_allowed_chat_ids and not self.settings.wecom_ai_allowed_user_ids:
            logger.warning("企业微信智能机器人白名单为空，联调期间允许所有群聊/用户触发")
        failures = 0
        while not self._stop:
            try:
                self._run_session()
                failures = 0
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                failures += 1
                delay = min(
                    self.settings.wecom_ai_reconnect_max_seconds,
                    self.settings.wecom_ai_reconnect_initial_seconds
                    * (2 ** min(failures - 1, 10)),
                )
                logger.error(
                    "企业微信智能机器人连接异常：%s；%.0f 秒后重连",
                    exc,
                    delay,
                )
                self._sleep(delay)

    def stop(self) -> None:
        self._stop = True

    def _run_session(self) -> None:
        with self._connect_factory(
            self.settings.wecom_ai_ws_url,
            proxy=None,
            ping_interval=None,
            open_timeout=10,
            close_timeout=10,
        ) as ws:
            logger.info("企业微信智能机器人已连接，开始订阅")
            self._subscribe(ws)
            last_heartbeat = time.monotonic()
            while not self._stop:
                now = time.monotonic()
                if (
                    now - last_heartbeat
                    >= self.settings.wecom_ai_heartbeat_seconds
                ):
                    self._send(
                        ws,
                        {
                            "cmd": "ping",
                            "headers": {"req_id": _new_req_id()},
                        },
                    )
                    last_heartbeat = now
                try:
                    raw = ws.recv(timeout=1)
                except TimeoutError:
                    continue
                if raw is None:
                    continue
                self._handle_frame(ws, raw)

    def _subscribe(self, ws: Any) -> None:
        req_id = _new_req_id()
        self._send(
            ws,
            {
                "cmd": "aibot_subscribe",
                "headers": {"req_id": req_id},
                "body": {
                    "bot_id": self.settings.wecom_ai_bot_id,
                    "secret": self.settings.wecom_ai_bot_secret,
                },
            },
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                raw = ws.recv(timeout=1)
            except TimeoutError:
                continue
            if raw is None:
                continue
            payload = _decode_frame(raw)
            headers = payload.get("headers") or {}
            if headers.get("req_id") != req_id:
                continue
            if payload.get("cmd") not in (None, "", "aibot_subscribe"):
                continue
            if payload.get("errcode") not in (None, 0):
                raise WeComAIConnectionError(
                    f"订阅失败：{payload.get('errmsg') or payload.get('errcode')}"
                )
            logger.info("企业微信智能机器人订阅成功")
            return
        raise WeComAIConnectionError("等待订阅响应超时")

    def _handle_frame(self, ws: Any, raw: Any) -> None:
        payload = _decode_frame(raw)
        if not isinstance(payload, dict):
            return
        cmd = str(payload.get("cmd") or "")
        if cmd == "aibot_msg_callback":
            self._handle_message(ws, payload)
        elif cmd == "aibot_event_callback":
            self._handle_event(payload)
        elif cmd in ("pong",):
            return
        elif payload.get("errcode") not in (None, 0):
            logger.warning(
                "企业微信智能机器人返回错误：%s",
                payload.get("errmsg") or payload.get("errcode"),
            )

    def _handle_message(self, ws: Any, payload: dict[str, Any]) -> None:
        message = parse_message_payload(payload)
        if message is None:
            logger.info(
                "收到不支持的企业微信消息类型，已忽略：%s",
                (payload.get("body") or {}).get("msgtype"),
            )
            return
        logger.info(
            "收到企业微信智能机器人消息：chat_id=%s userid=%s msgid=%s msgtype=%s",
            message.chat_id,
            message.from_userid,
            message.msgid,
            message.msg_type,
        )
        if message.aibot_id and message.aibot_id != self.settings.wecom_ai_bot_id:
            logger.info("企业微信消息来自未配置的机器人，已忽略：%s", message.aibot_id)
            return
        if not self._allowed(message):
            logger.info(
                "企业微信消息未通过白名单校验：chat_id=%s userid=%s",
                message.chat_id,
                message.from_userid,
            )
            return
        if message.chat_type == "group" and not has_bot_mention(
            message.content,
            self.settings.wecom_ai_bot_name,
        ):
            logger.info("企业微信群聊消息未 @ 机器人，已忽略")
            return
        if not message.msgid:
            logger.warning("企业微信消息缺少 msgid，已忽略")
            return
        question = strip_bot_mention(
            message.content,
            self.settings.wecom_ai_bot_name,
        )
        claimed = self.store.save_wecom_ai_message(
            msgid=message.msgid,
            req_id=message.req_id,
            chat_id=message.chat_id,
            chat_type=message.chat_type,
            from_userid=message.from_userid,
            msg_type=message.msg_type,
            content=message.content,
        )
        if claimed is None:
            logger.info("企业微信消息重复，已忽略：%s", message.msgid)
            return
        session_id = self._session_id(message)
        try:
            if not question:
                answer = "请问你想了解日报中的哪部分内容？"
                self.store.save_chat_message(
                    session_id,
                    "user",
                    message.content,
                    metadata={
                        "source": "wecom",
                        "chat_id": message.chat_id,
                        "user_id": message.from_userid,
                        "msgid": message.msgid,
                    },
                )
                self.store.save_chat_message(
                    session_id,
                    "assistant",
                    answer,
                    metadata={"source": "wecom"},
                )
            else:
                answer = self._answer_question(message, question, session_id)
            self._send_reply(ws, message.req_id, answer)
            self.store.mark_wecom_ai_message(
                message.msgid,
                "replied",
                answer=answer,
            )
        except Exception as exc:
            logger.exception("企业微信问答处理失败：%s", exc)
            fallback = _fallback_answer(exc)
            try:
                self._send_reply(ws, message.req_id, fallback)
            except Exception:
                logger.exception("企业微信降级回复发送失败")
            self.store.mark_wecom_ai_message(
                message.msgid,
                "failed",
                error=str(exc),
            )

    def _answer_question(
        self,
        message: WeComInboundMessage,
        question: str,
        session_id: str,
    ) -> str:
        report = self.store.load_latest()
        if report is None:
            answer = "暂无日报快照，请先生成日报后再提问。"
            self.store.save_chat_message(
                session_id,
                "user",
                message.content,
                metadata={
                    "source": "wecom",
                    "chat_id": message.chat_id,
                    "user_id": message.from_userid,
                    "msgid": message.msgid,
                },
            )
            self.store.save_chat_message(
                session_id,
                "assistant",
                answer,
                metadata={"source": "wecom"},
            )
            return answer
        history = self.store.load_chat_history(
            session_id,
            limit=self.settings.llm_chat_history_limit,
        )
        answer = self.llm_service.answer_question(
            report,
            question,
            history,
        )
        self.store.save_chat_message(
            session_id,
            "user",
            message.content,
            metadata={
                "source": "wecom",
                "chat_id": message.chat_id,
                "user_id": message.from_userid,
                "msgid": message.msgid,
            },
        )
        self.store.save_chat_message(
            session_id,
            "assistant",
            answer,
            metadata={"source": "wecom"},
        )
        return answer

    def _allowed(self, message: WeComInboundMessage) -> bool:
        if self.settings.wecom_ai_allowed_chat_ids and message.chat_id not in self.settings.wecom_ai_allowed_chat_ids:
            return False
        if self.settings.wecom_ai_allowed_user_ids and message.from_userid not in self.settings.wecom_ai_allowed_user_ids:
            return False
        return True

    def _handle_event(self, payload: dict[str, Any]) -> None:
        body = payload.get("body") or {}
        event = (body.get("event") or {}).get("eventtype", "")
        logger.info("收到企业微信智能机器人事件：%s", event or "unknown")

    def _send_reply(self, ws: Any, req_id: str, content: str) -> None:
        self._send(
            ws,
            {
                "cmd": "aibot_respond_msg",
                "headers": {"req_id": req_id},
                "body": {
                    "msgtype": "markdown",
                    "markdown": {"content": content[:_MAX_REPLY_CHARS]},
                },
            },
        )

    @staticmethod
    def _session_id(message: WeComInboundMessage) -> str:
        if message.chat_id:
            return f"wecom:{message.chat_id}:{message.from_userid}"
        return f"wecom:{message.from_userid}"

    @staticmethod
    def _send(ws: Any, payload: dict[str, Any]) -> None:
        ws.send(json.dumps(payload, ensure_ascii=False))


def _extract_content(body: dict[str, Any]) -> str:
    msg_type = body.get("msgtype", "")
    if msg_type == "text":
        text = body.get("text") or {}
        return str(text.get("content") or "").strip()
    if msg_type == "mixed":
        mixed = body.get("mixed") or {}
        lines: list[str] = []
        for item in mixed.get("msg_item") or []:
            if not isinstance(item, dict):
                continue
            if item.get("msgtype") == "text":
                text = item.get("text") or {}
                value = str(text.get("content") or "").strip()
                if value:
                    lines.append(value)
        return "\n".join(lines).strip()
    if msg_type == "voice":
        voice = body.get("voice") or {}
        return str(voice.get("content") or "").strip()
    return ""


def _extract_quote_text(body: dict[str, Any]) -> str:
    quote = body.get("quote") or {}
    if not isinstance(quote, dict):
        return ""
    msg_type = quote.get("msgtype", "")
    if msg_type == "text":
        text = quote.get("text") or {}
        return str(text.get("content") or "").strip()
    if msg_type == "mixed":
        mixed = quote.get("mixed") or {}
        lines: list[str] = []
        for item in mixed.get("msg_item") or []:
            if not isinstance(item, dict):
                continue
            if item.get("msgtype") == "text":
                text = item.get("text") or {}
                value = str(text.get("content") or "").strip()
                if value:
                    lines.append(value)
        return "\n".join(lines).strip()
    if msg_type == "voice":
        voice = quote.get("voice") or {}
        return str(voice.get("content") or "").strip()
    return ""


def _decode_frame(raw: Any) -> Any:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}


def _new_req_id() -> str:
    return secrets.token_urlsafe(16)


def _fallback_answer(exc: Exception) -> str:
    if isinstance(exc, LLMNotConfiguredError):
        return "当前问答服务未配置，请检查 LLM API Key。"
    if isinstance(exc, LLMError):
        return "抱歉，我暂时无法回答这个问题，请稍后再试。"
    return "抱歉，处理你的问题时出现异常，请稍后再试。"


def run_wecom_bot(
    settings: Settings | None = None,
    *,
    store: SnapshotStore | None = None,
    llm_service: Any | None = None,
    connect_factory: Any = None,
    sleep: Any = time.sleep,
) -> int:
    """Run the smart robot long-connection service as a standalone process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    bot = WeComAIBot(
        settings or load_settings(),
        store=store,
        llm_service=llm_service,
        connect_factory=connect_factory,
        sleep=sleep,
    )
    try:
        bot.run()
    except WeComAIConfigError as exc:
        logger.error("企业微信智能机器人配置错误：%s", exc)
        return 2
    except KeyboardInterrupt:
        print("企业微信智能机器人服务已停止")
        return 0
    return 0
