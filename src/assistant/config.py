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
DEFAULT_PUSH_CHANNELS = ["wechat_work"]


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
    push_channels: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PUSH_CHANNELS)
    )
    auth_token: str = ""
    web_require_auth: bool = False

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
        "push_channels",
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
    def validate_web_auth(self) -> "Settings":
        if self.web_require_auth and not self.auth_token.strip():
            raise ValueError(
                "公网访问要求鉴权（web_require_auth=true），"
                "但未配置 auth_token"
            )
        return self

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
