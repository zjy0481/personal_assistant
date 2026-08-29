from pathlib import Path

import pytest

from assistant.config import (
    DEFAULT_DATA_SOURCE_WHITELIST,
    DEFAULT_LOCATION,
    DEFAULT_PUSH_CHANNELS,
    DEFAULT_SOURCE_WHITELIST,
    DEFAULT_TIMEZONE,
    ConfigurationError,
    Settings,
    load_settings,
)


def test_load_settings_uses_default_configuration() -> None:
    settings = load_settings(env={})

    assert settings.location == DEFAULT_LOCATION
    assert settings.timezone == DEFAULT_TIMEZONE
    assert settings.data_source_whitelist == DEFAULT_DATA_SOURCE_WHITELIST
    assert settings.source_whitelist == DEFAULT_SOURCE_WHITELIST
    assert settings.push_channels == DEFAULT_PUSH_CHANNELS
    assert settings.auth_token == ""
    assert settings.web_require_auth is False


def test_load_settings_applies_explicit_environment_values() -> None:
    settings = load_settings(
        env={
            "ASSISTANT_LOCATION": "北京",
            "ASSISTANT_TIMEZONE": "Asia/Shanghai",
            "ASSISTANT_DATA_SOURCE_WHITELIST": "weather,news",
            "ASSISTANT_SOURCE_WHITELIST": "people,bbc",
            "ASSISTANT_PUSH_CHANNELS": '["wechat_work"]',
            "ASSISTANT_AUTH_TOKEN": "secret",
            "ASSISTANT_WEB_REQUIRE_AUTH": "true",
        }
    )

    assert settings.location == "北京"
    assert settings.timezone == "Asia/Shanghai"
    assert settings.data_source_whitelist == ["weather", "news"]
    assert settings.source_whitelist == ["people", "bbc"]
    assert settings.push_channels == ["wechat_work"]
    assert settings.auth_token == "secret"
    assert settings.web_require_auth is True


def test_settings_reads_dotenv_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "ASSISTANT_LOCATION=杭州",
                "ASSISTANT_TIMEZONE=Asia/Shanghai",
                "ASSISTANT_DATA_SOURCE_WHITELIST=[\"weather\",\"news\"]",
                "ASSISTANT_SOURCE_WHITELIST=[\"people\",\"bbc\"]",
                "ASSISTANT_PUSH_CHANNELS=[\"wechat_work\"]",
                "ASSISTANT_AUTH_TOKEN=dotenv-secret",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.location == "杭州"
    assert settings.timezone == "Asia/Shanghai"
    assert settings.data_source_whitelist == ["weather", "news"]
    assert settings.source_whitelist == ["people", "bbc"]
    assert settings.push_channels == ["wechat_work"]
    assert settings.auth_token == "dotenv-secret"
    assert settings.web_require_auth is False


def test_load_settings_reads_default_toml_from_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "config.toml").write_text(
        "\n".join(
            [
                'location = "广州"',
                'timezone = "Asia/Shanghai"',
                'data_source_whitelist = ["weather"]',
                'source_whitelist = ["people"]',
                'push_channels = ["wechat_work"]',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = load_settings()

    assert settings.location == "广州"
    assert settings.data_source_whitelist == ["weather"]
    assert settings.source_whitelist == ["people"]
    assert settings.push_channels == ["wechat_work"]


def test_load_settings_reads_toml_config_file(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "\n".join(
            [
                'location = "深圳"',
                'timezone = "Asia/Shanghai"',
                'data_source_whitelist = ["weather", "news"]',
                'source_whitelist = ["people", "bbc"]',
                'push_channels = ["wechat_work"]',
                'auth_token = "file-secret"',
                'web_require_auth = true',
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(env={}, config_file=config_file)

    assert settings.location == "深圳"
    assert settings.timezone == "Asia/Shanghai"
    assert settings.data_source_whitelist == ["weather", "news"]
    assert settings.source_whitelist == ["people", "bbc"]
    assert settings.push_channels == ["wechat_work"]
    assert settings.auth_token == "file-secret"
    assert settings.web_require_auth is True


def test_environment_values_override_config_file(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        'location = "上海"\ntimezone = "Asia/Shanghai"',
        encoding="utf-8",
    )

    settings = load_settings(
        env={"ASSISTANT_LOCATION": "北京"},
        config_file=config_file,
    )

    assert settings.location == "北京"
    assert settings.timezone == "Asia/Shanghai"


def test_load_settings_raises_for_missing_explicit_config_file(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigurationError, match="配置文件不存在"):
        load_settings(
            env={},
            config_file=tmp_path / "missing.toml",
        )


def test_load_settings_raises_when_public_auth_token_is_missing() -> None:
    with pytest.raises(ConfigurationError, match="auth_token"):
        load_settings(
            env={"ASSISTANT_WEB_REQUIRE_AUTH": "true"},
        )


def test_load_settings_raises_for_invalid_timezone() -> None:
    with pytest.raises(ConfigurationError, match="无效时区"):
        load_settings(
            env={"ASSISTANT_TIMEZONE": "Mars/Olympus"},
        )


def test_settings_is_a_public_value_object() -> None:
    settings = Settings(
        location="深圳",
        timezone="Asia/Shanghai",
        data_source_whitelist=["weather"],
        source_whitelist=["people"],
        push_channels=["wechat_work"],
        auth_token="local-secret",
    )

    assert settings.location == "深圳"
    assert settings.timezone == "Asia/Shanghai"
    assert settings.data_source_whitelist == ["weather"]
    assert settings.source_whitelist == ["people"]
    assert settings.push_channels == ["wechat_work"]
    assert settings.auth_token == "local-secret"