"""Application configuration."""

import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import TomlConfigSettingsSource

ENV_PREFIX = "ASSISTANT_"
DEFAULT_CONFIG_FILE = "config.toml"
DEFAULT_LOCATION = "上海"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_DATA_SOURCE_WHITELIST = ["weather", "news", "github", "ai"]
DEFAULT_PUSH_CHANNELS = ["wecom_group", "pushplus"]
DEFAULT_SOURCE_WHITELIST = [
    "people",
    "chinanews",
    "openai",
    "deepmind",
    "qbitai",
]
DEFAULT_WEATHER_ALERT_TYPES = [
    "台风",
    "暴雨",
    "高温",
    "寒潮",
    "大风",
    "雷电",
    "雷雨大风",
    "大雾",
    "沙尘暴",
    "强对流",
    "暴雪",
    "道路结冰",
]


class ConfigurationError(RuntimeError):
    """Raised when required configuration cannot be loaded or is invalid."""


class Settings(BaseSettings):
    """User-facing configuration for the personal assistant.

    ``location`` is the single source of truth for the configured weather
    region. Both the daily weather content block and the web surface must read
    this value instead of keeping their own location settings.
    """

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        toml_file=DEFAULT_CONFIG_FILE,
    )

    location: str = DEFAULT_LOCATION
    timezone: str = DEFAULT_TIMEZONE
    data_source_whitelist: list[str] = Field(
        default_factory=lambda: list(DEFAULT_DATA_SOURCE_WHITELIST)
    )
    source_whitelist: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SOURCE_WHITELIST)
    )
    push_channels: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PUSH_CHANNELS)
    )
    pushplus_token: str = ""
    wecom_group_webhook: str = ""
    push_max_items: int = Field(default=5, ge=1, le=50)
    push_mock: bool = False
    daily_retry_max: int = Field(default=3, ge=1, le=10)
    daily_retry_interval_seconds: int = Field(default=30, ge=1, le=600)
    auth_token: str = ""
    web_require_auth: bool = False
    wecom_corpid: str = ""
    wecom_agentid: str = ""
    wecom_secret: str = ""
    wecom_userid: str = ""
    web_url: str = "http://127.0.0.1:8000/"
    wecom_mock: bool = False
    wecom_ai_enabled: bool = False
    wecom_ai_mode: str = "long_connection"
    wecom_ai_bot_id: str = ""
    wecom_ai_bot_secret: str = ""
    wecom_ai_bot_name: str = ""
    wecom_ai_allowed_chat_ids: list[str] = Field(default_factory=list)
    wecom_ai_allowed_user_ids: list[str] = Field(default_factory=list)
    wecom_ai_ws_url: str = "wss://openws.work.weixin.qq.com"
    wecom_ai_callback_url: str = ""
    wecom_ai_token: str = ""
    wecom_ai_encoding_aes_key: str = ""
    wecom_ai_heartbeat_seconds: int = Field(default=30, ge=5, le=120)
    wecom_ai_reconnect_initial_seconds: int = Field(default=1, ge=1, le=60)
    wecom_ai_reconnect_max_seconds: int = Field(default=60, ge=5, le=600)
    wecom_ai_retention_days: int = Field(default=180, ge=1, le=3650)
    llm_provider: str = "deepseek"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"
    llm_timeout_seconds: int = Field(default=30, ge=1, le=300)
    llm_daily_limit: int = Field(default=300, ge=1)
    llm_minute_limit: int = Field(default=30, ge=1)
    llm_failure_threshold: int = Field(default=3, ge=1, le=10)
    llm_circuit_breaker_seconds: int = Field(default=60, ge=1)
    llm_summary_enabled: bool = True
    llm_max_items: int = Field(default=30, ge=1, le=200)
    llm_chat_history_limit: int = Field(default=50, ge=1, le=100)
    llm_chat_retention_days: int = Field(default=7, ge=1, le=90)
    trend_retention_days: int = Field(default=180, ge=1, le=3650)
    news_trend_min_count: int = Field(default=1, ge=1, le=20)
    weather_alert_enabled: bool = True
    weather_alert_locations: list[str] = Field(default_factory=list)
    weather_alert_interval_seconds: int = Field(default=600, ge=60, le=86400)
    weather_alert_types: list[str] = Field(default_factory=list)
    weather_alert_retention_days: int = Field(default=180, ge=1, le=3650)
    weather_alert_timeout_seconds: int = Field(default=12, ge=3, le=60)
    weather_alert_retry_max: int = Field(default=3, ge=1, le=10)
    weather_alert_failure_threshold: int = Field(default=3, ge=1, le=20)
    weather_alert_failure_pause_minutes: int = Field(
        default=60,
        ge=1,
        le=1440,
    )
    qweather_api_key: str = ""
    qweather_token: str = ""
    qweather_api_host: str = "https://api.qweather.com"
    qweather_location_id: str = ""
    qweather_latitude: float | None = Field(default=None, ge=-90, le=90)
    qweather_longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("location")
    @classmethod
    def validate_location(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("地区配置不能为空（location）")
        return value.strip()

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                f"无效时区: {value!r}，请使用 IANA 时区名，例如 Asia/Shanghai"
            ) from exc
        return value

    @field_validator(
        "data_source_whitelist",
        "source_whitelist",
        "push_channels",
        "weather_alert_locations",
        "weather_alert_types",
        "wecom_ai_allowed_chat_ids",
        "wecom_ai_allowed_user_ids",
        mode="before",
    )
    @classmethod
    def parse_list_values(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            if text.startswith("["):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        "列表配置必须使用 JSON 数组，例如 "
                        '["weather", "news"]'
                    ) from exc
                if not isinstance(parsed, list):
                    raise ValueError("列表配置必须解析为数组")
                return [str(item).strip() for item in parsed]
            return [item.strip() for item in text.split(",") if item.strip()]
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value]
        raise ValueError("列表配置必须是数组或逗号分隔的字符串")

    @model_validator(mode="after")
    def validate_wecom_ai(self) -> "Settings":
        if not self.wecom_ai_active:
            return self
        if self.wecom_ai_mode not in ("long_connection", "callback"):
            raise ValueError("wecom_ai_mode 仅支持 long_connection 或 callback")
        if self.wecom_ai_mode == "long_connection":
            if not self.wecom_ai_bot_id.strip() or not self.wecom_ai_bot_secret.strip():
                raise ValueError("长连接模式必须配置 wecom_ai_bot_id 和 wecom_ai_bot_secret")
        else:
            if not self.wecom_ai_callback_url.strip() or not self.wecom_ai_token.strip() or not self.wecom_ai_encoding_aes_key.strip():
                raise ValueError("回调模式必须配置 callback_url、token、encoding_aes_key")
        return self
    @model_validator(mode="after")
    def validate_web_auth(self) -> "Settings":
        if self.web_require_auth and not self.auth_token.strip():
            raise ValueError(
                "公网访问要求鉴权（web_require_auth=true），"
                "但未配置 auth_token"
            )
        if (self.qweather_latitude is None) != (
            self.qweather_longitude is None
        ):
            raise ValueError(
                "qweather_latitude 和 qweather_longitude 必须同时配置"
            )
        return self

    @property
    def wecom_ai_active(self) -> bool:
        return self.wecom_ai_enabled or bool(
            self.wecom_ai_bot_id.strip() and self.wecom_ai_bot_secret.strip()
        )

    @property
    def alert_locations(self) -> list[str]:
        return list(self.weather_alert_locations) or [self.location]

    @property
    def active_weather_alert_types(self) -> list[str]:
        return list(self.weather_alert_types) or list(DEFAULT_WEATHER_ALERT_TYPES)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        """Load TOML after environment vars so explicit values keep priority."""

        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


def _normalize_env(env: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key.removeprefix(ENV_PREFIX).lower(): value
        for key, value in env.items()
        if key.startswith(ENV_PREFIX)
    }


def _read_config_file(config_file: Path) -> dict[str, Any]:
    try:
        with config_file.open("rb") as file:
            return tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(
            f"配置文件解析失败: {config_file}；请检查 TOML 语法"
        ) from exc


def _build_settings(**values: Any) -> Settings:
    try:
        return Settings(_env_file=None, **values)
    except ValidationError as exc:
        raise ConfigurationError(f"配置无效: {exc}") from exc


def load_settings(
    env: Mapping[str, Any] | None = None,
    config_file: str | Path | None = None,
) -> Settings:
    """Load settings from ``.env``/process env and an optional TOML file.

    Without explicit arguments, ``config.toml`` in the current directory is
    loaded when present, so a fresh checkout can still start with defaults.
    An explicitly requested missing config file is treated as a startup error.
    """

    if env is None and config_file is None:
        try:
            return Settings()
        except ValidationError as exc:
            raise ConfigurationError(f"配置无效: {exc}") from exc

    file_values: dict[str, Any] = {}
    if config_file is not None:
        path = Path(config_file).expanduser()
        if not path.is_file():
            raise ConfigurationError(
                f"配置文件不存在: {path}；请根据 config.example.toml "
                "创建 config.toml"
            )
        file_values = _read_config_file(path)

    env_values = _normalize_env(env or {})
    return _build_settings(**{**file_values, **env_values})
