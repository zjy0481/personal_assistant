"""Open-Meteo weather source and weather content block."""

from typing import Any

import httpx

from assistant.models import ContentBlock
from assistant.sources.base import DataSourceError

WEATHER_CODE_DESCRIPTIONS = {
    0: "晴",
    1: "大部晴朗",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "强毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "小阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴冰雹",
    99: "强雷暴伴冰雹",
}


def _description(code: int | None) -> str:
    if code is None:
        return "未知"
    return WEATHER_CODE_DESCRIPTIONS.get(code, "未知")


class OpenMeteoWeatherSource:
    """Fetch current, daily forecast and air quality from Open-Meteo."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            timeout=10.0,
            follow_redirects=True,
        )

    def fetch(self, location: str, timezone: str) -> ContentBlock:
        try:
            coordinates = self._geocode(location)
            forecast = self._forecast(
                coordinates["latitude"],
                coordinates["longitude"],
                timezone,
            )
            air_quality = self._air_quality(
                coordinates["latitude"],
                coordinates["longitude"],
                timezone,
            ) or {}

            return ContentBlock(
                kind="weather",
                title=f"{location}天气",
                status="ok",
                details={
                    "location": location,
                    "timezone": timezone,
                    "current": {
                        **forecast["current"],
                        **air_quality,
                    },
                    "days": forecast["days"],
                },
                sources=["Open-Meteo"],
            )
        except Exception as exc:
            return ContentBlock(
                kind="weather",
                title=f"{location}天气",
                status="failed",
                sources=["Open-Meteo"],
                message=f"天气数据源不可用: {exc}",
            )

    def _geocode(self, location: str) -> dict[str, Any]:
        response = self.client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={
                "name": location,
                "count": 1,
                "language": "zh",
                "format": "json",
            },
        )
        response.raise_for_status()
        results = response.json().get("results") or []
        if not results:
            raise DataSourceError(f"未找到天气地区: {location}")
        return results[0]

    def _forecast(
        self,
        latitude: float,
        longitude: float,
        timezone: str,
    ) -> dict[str, Any]:
        response = self.client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": (
                    "temperature_2m,relative_humidity_2m,"
                    "apparent_temperature,is_day,precipitation,"
                    "weather_code,wind_speed_10m,wind_direction_10m"
                ),
                "daily": (
                    "weather_code,temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max,wind_speed_10m_max"
                ),
                "timezone": timezone,
                "forecast_days": 3,
            },
        )
        response.raise_for_status()
        payload = response.json()
        current = payload.get("current") or {}
        daily = payload.get("daily") or {}
        if not current or not daily.get("time"):
            raise DataSourceError("Open-Meteo 返回的实时或预报数据为空")

        current_data = {
            "temperature": current.get("temperature_2m"),
            "apparent_temperature": current.get("apparent_temperature"),
            "humidity": current.get("relative_humidity_2m"),
            "weather_code": current.get("weather_code"),
            "description": _description(current.get("weather_code")),
            "is_day": bool(current.get("is_day")),
            "precipitation": current.get("precipitation"),
            "precipitation_probability": (
                daily["precipitation_probability_max"][0]
                if len(daily.get("precipitation_probability_max", [])) > 0
                else None
            ),
            "wind_speed": current.get("wind_speed_10m"),
            "wind_direction": current.get("wind_direction_10m"),
        }

        times = daily.get("time", [])
        days = []
        for index, day in enumerate(times):
            days.append(
                {
                    "date": day,
                    "weather_code": daily["weather_code"][index]
                    if len(daily.get("weather_code", [])) > index
                    else None,
                    "description": _description(
                        daily["weather_code"][index]
                        if len(daily.get("weather_code", [])) > index
                        else None
                    ),
                    "temp_min": daily["temperature_2m_min"][index]
                    if len(daily.get("temperature_2m_min", [])) > index
                    else None,
                    "temp_max": daily["temperature_2m_max"][index]
                    if len(daily.get("temperature_2m_max", [])) > index
                    else None,
                    "precipitation_probability": (
                        daily["precipitation_probability_max"][index]
                        if len(
                            daily.get("precipitation_probability_max", [])
                        )
                        > index
                        else None
                    ),
                    "wind_speed_max": daily["wind_speed_10m_max"][index]
                    if len(daily.get("wind_speed_10m_max", [])) > index
                    else None,
                }
            )

        return {"current": current_data, "days": days}

    def _air_quality(
        self,
        latitude: float,
        longitude: float,
        timezone: str,
    ) -> dict[str, Any] | None:
        try:
            response = self.client.get(
                "https://air-quality-api.open-meteo.com/v1/air-quality",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "us_aqi,pm2_5",
                    "timezone": timezone,
                },
            )
            response.raise_for_status()
            current = response.json().get("current") or {}
            return {
                "air_quality_aqi": current.get("us_aqi"),
                "pm2_5": current.get("pm2_5"),
            }
        except Exception:
            return None