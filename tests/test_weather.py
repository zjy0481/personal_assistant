import httpx

from assistant.sources.weather import OpenMeteoWeatherSource


def _weather_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "geocoding-api" in url:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "name": "上海",
                            "latitude": 31.2304,
                            "longitude": 121.4737,
                        }
                    ]
                },
            )
        if "air-quality" in url:
            return httpx.Response(
                200,
                json={
                    "current": {
                        "us_aqi": 67,
                        "pm2_5": 12.3,
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "current": {
                    "temperature_2m": 25.0,
                    "relative_humidity_2m": 70,
                    "apparent_temperature": 26.0,
                    "is_day": 1,
                    "precipitation": 0.0,
                    "weather_code": 1,
                    "wind_speed_10m": 12.0,
                    "wind_direction_10m": 120,
                },
                "daily": {
                    "time": ["2026-08-28", "2026-08-29", "2026-08-30"],
                    "weather_code": [0, 2, 3],
                    "temperature_2m_max": [30.0, 31.0, 29.0],
                    "temperature_2m_min": [22.0, 23.0, 21.0],
                    "precipitation_probability_max": [10, 20, 30],
                    "wind_speed_10m_max": [15.0, 18.0, 14.0],
                },
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_weather_source_returns_today_and_next_two_days() -> None:
    source = OpenMeteoWeatherSource(client=_weather_client())

    block = source.fetch("上海", "Asia/Shanghai")

    assert block.kind == "weather"
    assert block.status == "ok"
    assert block.details["current"]["temperature"] == 25.0
    assert block.details["current"]["air_quality_aqi"] == 67
    assert block.details["days"][0]["description"] == "晴"
    assert len(block.details["days"]) == 3


def test_weather_source_failure_returns_failed_block() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network unavailable")

    source = OpenMeteoWeatherSource(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    block = source.fetch("上海", "Asia/Shanghai")

    assert block.kind == "weather"
    assert block.status == "failed"
    assert block.message is not None
    assert "network unavailable" in block.message