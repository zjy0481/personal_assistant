import pytest

from assistant.config import (
    DEFAULT_PUSH_CHANNELS,
    ConfigurationError,
    Settings,
    load_settings,
)


def test_default_push_channels_are_wecom_group_then_pushplus() -> None:
    assert DEFAULT_PUSH_CHANNELS == ["wecom_group", "pushplus"]


def test_settings_carries_pushplus_and_group_webhook_configuration() -> None:
    settings = Settings(
        location="上海",
        timezone="Asia/Shanghai",
        push_channels=["wecom_group", "pushplus"],
        pushplus_token="pushplus-token",
        wecom_group_webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
        push_max_items=8,
        push_mock=False,
    )

    assert settings.push_channels == ["wecom_group", "pushplus"]
    assert settings.pushplus_token == "pushplus-token"
    assert settings.wecom_group_webhook == (
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc"
    )
    assert settings.push_max_items == 8
    assert settings.push_mock is False


def test_load_settings_reads_pushplus_and_webhook_from_env() -> None:
    settings = load_settings(
        env={
            "ASSISTANT_PUSH_CHANNELS": '["wecom_group","pushplus"]',
            "ASSISTANT_PUSHPLUS_TOKEN": "env-token",
            "ASSISTANT_WECOM_GROUP_WEBHOOK": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=env-key",
            "ASSISTANT_PUSH_MAX_ITEMS": "6",
            "ASSISTANT_PUSH_MOCK": "false",
        }
    )

    assert settings.push_channels == ["wecom_group", "pushplus"]
    assert settings.pushplus_token == "env-token"
    assert settings.wecom_group_webhook == (
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=env-key"
    )
    assert settings.push_max_items == 6
    assert settings.push_mock is False


def test_settings_carries_daily_retry_configuration() -> None:
    settings = Settings(
        location="上海",
        timezone="Asia/Shanghai",
        daily_retry_max=3,
        daily_retry_interval_seconds=30,
    )
    assert settings.daily_retry_max == 3
    assert settings.daily_retry_interval_seconds == 30

def test_push_max_items_must_be_positive() -> None:
    with pytest.raises(ConfigurationError):
        load_settings(env={"ASSISTANT_PUSH_MAX_ITEMS": "0"})
