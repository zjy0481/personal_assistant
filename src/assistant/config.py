"""Application configuration."""

from collections.abc import Mapping

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "ASSISTANT_"


class Settings(BaseSettings):
    """User-facing configuration for the personal assistant."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    location: str = "上海"
    timezone: str = "Asia/Shanghai"


def load_settings(
    env: Mapping[str, str] | None = None,
) -> Settings:
    """Load settings from an explicit mapping, falling back to environment and .env."""

    if env is None:
        return Settings()

    normalized = {
        key.removeprefix(ENV_PREFIX): value
        for key, value in env.items()
    }
    return Settings(_env_file=None, **normalized)
