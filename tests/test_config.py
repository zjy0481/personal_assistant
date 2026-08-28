from assistant.config import Settings, load_settings


def test_load_settings_uses_default_shanghai_location() -> None:
    settings = load_settings(env={})

    assert settings.location == "上海"


def test_load_settings_applies_explicit_environment_values() -> None:
    settings = load_settings(
        env={
            "ASSISTANT_LOCATION": "北京",
            "ASSISTANT_TIMEZONE": "Asia/Shanghai",
        }
    )

    assert settings.location == "北京"
    assert settings.timezone == "Asia/Shanghai"


def test_settings_is_a_public_value_object() -> None:
    settings = Settings(
        location="深圳",
        timezone="Asia/Shanghai",
    )

    assert settings.location == "深圳"
    assert settings.timezone == "Asia/Shanghai"
