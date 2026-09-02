"""Extreme weather warning sources used by the independent alert monitor."""

import html
import re
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx

from assistant.config import Settings
from assistant.models import WeatherAlert
from assistant.sources.base import DataSourceError

SOURCE_NMC = "nmc"
SOURCE_QWEATHER = "qweather"
NMC_BASE_URL = "https://www.nmc.cn"
QWEATHER_LEGACY_HOST = "https://devapi.qweather.com"
QWEATHER_GEO_HOST = "https://geoapi.qweather.com"
CN_TZ = ZoneInfo("Asia/Shanghai")
LEVEL_RANK = {
    "未知": 0,
    "蓝色": 1,
    "黄色": 2,
    "橙色": 3,
    "红色": 4,
}
NMC_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Referer": "https://www.nmc.cn/",
    "Accept": "application/json,text/plain,*/*",
}
_CHINESE_TIME_RE = re.compile(
    r"(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2})时(\d{1,2})分"
)
_URL_ALERT_TIME_RE = re.compile(r"_(\d{14})\.html$")
_ALERT_ID_RE = re.compile(r"/alarm/([A-Za-z0-9_]+)\.html$")


class WeatherWarningSource:
    """Boundary for a source that returns current warnings per location."""

    name = ""

    def fetch(self, locations: list[str]) -> list[WeatherAlert]:
        raise NotImplementedError


class NmcWarningSource(WeatherWarningSource):
    """Read NMC alerts from the public alarm list and city weather endpoint."""

    name = SOURCE_NMC

    def __init__(
        self,
        client: httpx.Client | None = None,
        timeout: float = 12.0,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers=NMC_HEADERS,
        )
        self._station_cache: dict[str, dict[str, str]] = {}
        self._stations: list[dict[str, str]] | None = None

    def fetch(self, locations: list[str]) -> list[WeatherAlert]:
        try:
            alerts = self._fetch_alarm_alerts(locations)
            if alerts:
                return alerts
        except Exception:
            pass

        alerts: list[WeatherAlert] = []
        for location in locations:
            try:
                station = self._resolve_station(location)
                payload = self._weather(station["code"])
                alert = self._parse_weather_payload(payload, location)
                if alert is not None:
                    alerts.append(alert)
            except Exception as exc:
                raise DataSourceError(
                    f"中央气象台获取 {location} 预警失败: {exc}"
                ) from exc
        return alerts

    def _fetch_alarm_alerts(
        self,
        locations: list[str],
    ) -> list[WeatherAlert]:
        payload = self._get_json(
            "/rest/findAlarm",
            params={"pageNo": "1", "pageSize": "1000"},
        )
        data = payload.get("data") or {}
        page = data.get("page") or {}
        items = list(page.get("list") or []) + list(
            data.get("provinceAlarms") or []
        )
        best: dict[
            tuple[str, str],
            tuple[datetime | None, dict[str, Any]],
        ] = {}
        for location in locations:
            normalized = _normalize_name(location)
            for item in items:
                title = _clean_value(item.get("title"))
                if normalized not in _normalize_name(title):
                    continue
                alert_type = _parse_alert_type(title)
                if alert_type == "其它":
                    continue
                issued = _parse_nmc_issue_time(item.get("issuetime"))
                key = (location, alert_type)
                previous = best.get(key)
                replace = previous is None
                if not replace and issued:
                    replace = previous[0] is None or issued > previous[0]
                if replace:
                    best[key] = (issued, item)

        alerts: list[WeatherAlert] = []
        for (location, alert_type), (issued, item) in best.items():
            alert = self._parse_alarm_item(
                item,
                location=location,
                alert_type=alert_type,
                issued=issued,
            )
            if alert is not None:
                self._enrich_alarm_detail(alert)
                alerts.append(alert)
        return alerts

    def _parse_alarm_item(
        self,
        item: dict[str, Any],
        *,
        location: str,
        alert_type: str,
        issued: datetime | None,
    ) -> WeatherAlert | None:
        title = _clean_value(item.get("title"))
        if not title:
            return None
        source_url = _absolute_url(_clean_value(item.get("url")))
        alert_id = str(
            item.get("alertid")
            or _alert_id_from_url(source_url)
            or title
        )
        return WeatherAlert(
            alert_id=alert_id,
            location=location,
            alert_type=alert_type,
            level=normalize_level(title),
            title=title,
            description=title,
            safety_guidance="",
            status="active",
            published_at=issued,
            started_at=issued,
            ended_at=None,
            source=SOURCE_NMC,
            source_url=source_url,
            raw=dict(item),
        )

    def _enrich_alarm_detail(self, alert: WeatherAlert) -> None:
        if not alert.source_url:
            return
        try:
            response = self.client.get(alert.source_url)
            response.raise_for_status()
            description, safety = _parse_alarm_html(response.text)
            if description:
                alert.description = description
            if safety:
                alert.safety_guidance = safety
            else:
                alert.safety_guidance = _default_warning_safety(
                    alert.alert_type
                )
        except Exception:
            alert.safety_guidance = (
                alert.safety_guidance
                or _default_warning_safety(alert.alert_type)
            )

    def _resolve_station(self, location: str) -> dict[str, str]:
        cached = self._station_cache.get(location)
        if cached:
            return cached
        normalized = _normalize_name(location)
        matches = [
            station
            for station in self._load_stations()
            if normalized == _normalize_name(station["city"])
            or normalized in _normalize_name(station["city"])
            or _normalize_name(station["city"]) in normalized
        ]
        if not matches:
            raise DataSourceError(f"中央气象台未找到地区: {location}")
        exact = [
            station
            for station in matches
            if station["city"].strip() == location.strip()
        ]
        station = exact[0] if len(exact) == 1 else matches[0]
        self._station_cache[location] = station
        return station

    def _load_stations(self) -> list[dict[str, str]]:
        if self._stations is not None:
            return self._stations
        provinces = self._get_json("/rest/province/all")
        if not isinstance(provinces, list):
            raise DataSourceError("中央气象台省级列表格式不正确")
        stations: list[dict[str, str]] = []
        for province in provinces:
            code = str(province.get("code") or "")
            city_rows = self._get_json(f"/rest/province/{code}")
            if not isinstance(city_rows, list):
                continue
            for city in city_rows:
                if city.get("code") and city.get("city"):
                    stations.append(
                        {
                            "code": str(city["code"]),
                            "province": str(city.get("province") or ""),
                            "city": str(city["city"]),
                        }
                    )
        self._stations = stations
        return stations

    def _weather(self, station_id: str) -> dict[str, Any]:
        payload = self._get_json(
            "/rest/weather",
            params={"stationid": station_id},
        )
        if payload.get("code") != 0 or not payload.get("data"):
            raise DataSourceError(
                f"中央气象台天气接口返回 code={payload.get('code')}"
            )
        return payload

    def _parse_weather_payload(
        self,
        payload: dict[str, Any],
        location: str,
    ) -> WeatherAlert | None:
        real = (payload.get("data") or {}).get("real") or {}
        warn = real.get("warn") or {}
        if _is_missing(warn.get("alert")) and _is_missing(
            warn.get("issuecontent")
        ):
            return None
        title = _clean_value(warn.get("alert"))
        if not title:
            title = "气象预警信号"
        source_url = _absolute_url(_clean_value(warn.get("url")))
        alert_id = _alert_id_from_url(source_url) or title
        alert_type = _clean_value(warn.get("signaltype"))
        if not alert_type:
            alert_type = _parse_alert_type(title)
        level = normalize_level(warn.get("signallevel"))
        description = _clean_value(warn.get("issuecontent")) or title
        safety_guidance = _clean_value(warn.get("fmeans"))
        published_at = (
            _alert_time_from_url(source_url)
            or _parse_chinese_time(description)
            or _parse_datetime(real.get("publish_time"))
        )
        return WeatherAlert(
            alert_id=alert_id,
            location=location,
            alert_type=alert_type,
            level=level,
            title=title,
            description=description,
            safety_guidance=safety_guidance,
            status="active",
            published_at=published_at,
            started_at=published_at,
            ended_at=None,
            source=SOURCE_NMC,
            source_url=source_url,
            raw=dict(warn),
        )

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> Any:
        url = NMC_BASE_URL + path
        try:
            response = self.client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise DataSourceError(f"请求失败 {url}: {exc}") from exc
        if not isinstance(payload, (dict, list)):
            raise DataSourceError(f"响应不是 JSON 对象: {url}")
        return payload

class QWeatherWarningSource(WeatherWarningSource):
    """Return current warnings from QWeather's legacy or v1 API."""

    name = SOURCE_QWEATHER

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
        timeout: float = 12.0,
        *,
        api_key: str | None = None,
        token: str | None = None,
        api_host: str | None = None,
        location_id: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
        )
        self.api_key = api_key or (settings.qweather_api_key if settings else "")
        self.token = token or (settings.qweather_token if settings else "")
        self.api_host = (
            api_host
            or (settings.qweather_api_host if settings else "")
            or "https://api.qweather.com"
        ).rstrip("/")
        self.location_id = (
            location_id
            or (settings.qweather_location_id if settings else "")
        )
        self.latitude = (
            latitude
            if latitude is not None
            else (settings.qweather_latitude if settings else None)
        )
        self.longitude = (
            longitude
            if longitude is not None
            else (settings.qweather_longitude if settings else None)
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key or self.token)

    def fetch(self, locations: list[str]) -> list[WeatherAlert]:
        if not self.configured:
            raise DataSourceError(
                "和风天气配置缺失：qweather_api_key 或 qweather_token"
            )
        alerts: list[WeatherAlert] = []
        for location in locations:
            try:
                if self.token:
                    latitude, longitude = self._coordinates(location)
                    alerts.extend(
                        self._fetch_current(location, latitude, longitude)
                    )
                else:
                    location_id = self._resolved_location_id(location)
                    alerts.extend(self._fetch_v7(location, location_id))
            except Exception as exc:
                raise DataSourceError(
                    f"和风天气获取 {location} 预警失败: {exc}"
                ) from exc
        return alerts

    def _coordinates(self, location: str) -> tuple[float, float]:
        if self.latitude is not None and self.longitude is not None:
            return float(self.latitude), float(self.longitude)
        result = self._geo_lookup(location)
        latitude = result.get("lat")
        longitude = result.get("lon")
        if latitude is None or longitude is None:
            raise DataSourceError(
                f"和风天气未找到经纬度: {location}"
            )
        return float(latitude), float(longitude)

    def _resolved_location_id(self, location: str) -> str:
        if self.location_id:
            return self.location_id
        result = self._geo_lookup(location)
        location_id = result.get("id")
        if not location_id:
            raise DataSourceError(f"和风天气未找到地区编码: {location}")
        return str(location_id)

    def _geo_lookup(self, location: str) -> dict[str, Any]:
        response = self.client.get(
            QWEATHER_GEO_HOST + "/v2/city/lookup",
            params={"location": location, "key": self.api_key},
        )
        payload = self._json_response(response)
        if payload.get("code") not in (200, "200"):
            raise DataSourceError(
                f"和风天气城市查询 code={payload.get('code')}, "
                f"msg={payload.get('message', payload.get('error', ''))}"
            )
        rows = payload.get("location") or []
        if not rows:
            raise DataSourceError(f"和风天气未找到城市: {location}")
        return dict(rows[0])

    def _fetch_current(
        self,
        location: str,
        latitude: float,
        longitude: float,
    ) -> list[WeatherAlert]:
        response = self.client.get(
            f"{self.api_host}/weatheralert/v1/current/"
            f"{latitude}/{longitude}",
            params={"localTime": "true"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        payload = self._json_response(response)
        if payload.get("error"):
            raise DataSourceError(
                f"和风天气预警响应错误: {payload['error']}"
            )
        alerts = payload.get("alerts") or []
        return [
            parsed
            for item in alerts
            if (parsed := self._parse_v1(location, item)) is not None
        ]

    def _fetch_v7(
        self,
        location: str,
        location_id: str,
    ) -> list[WeatherAlert]:
        response = self.client.get(
            QWEATHER_LEGACY_HOST + "/v7/warning/now",
            params={"location": location_id, "key": self.api_key},
        )
        payload = self._json_response(response)
        if payload.get("code") not in (200, "200"):
            raise DataSourceError(
                f"和风天气预警登录 code={payload.get('code')}, "
                f"msg={payload.get('message', payload.get('error', ''))}"
            )
        raw_alerts = payload.get("warning") or payload.get("alerts") or []
        if isinstance(raw_alerts, dict):
            raw_alerts = [raw_alerts]
        return [
            parsed
            for item in raw_alerts
            if (parsed := self._parse_v7(location, item)) is not None
        ]

    @staticmethod
    def _parse_v1(location: str, item: dict[str, Any]) -> WeatherAlert | None:
        message_type = item.get("messageType") or {}
        code = message_type.get("code") or ""
        if code == "cancel":
            return None
        event_type = item.get("eventType") or {}
        alert_type = _clean_value(event_type.get("name")) or _parse_alert_type(
            _clean_value(item.get("headline"))
        )
        if not alert_type:
            return None
        color = item.get("color") or {}
        level = normalize_level(color.get("code") or item.get("severity"))
        title = _clean_value(item.get("headline")) or alert_type + "预警"
        description = _clean_value(item.get("description")) or title
        safety_guidance = _clean_value(item.get("instruction"))
        superseded = list(message_type.get("supersedes") or [])
        alert_id = str(superseded[0] if superseded else item.get("id") or "")
        return WeatherAlert(
            alert_id=alert_id,
            location=location,
            alert_type=alert_type,
            level=level,
            title=title,
            description=description,
            safety_guidance=safety_guidance,
            status="active",
            published_at=_parse_datetime(item.get("issuedTime")),
            started_at=_parse_datetime(
                item.get("effectiveTime") or item.get("onsetTime")
            ),
            ended_at=_parse_datetime(item.get("expireTime")),
            source=SOURCE_QWEATHER,
            source_url=_clean_value(item.get("source"))
            or "https://dev.qweather.com/",
            raw=dict(item),
        )

    @staticmethod
    def _parse_v7(location: str, item: dict[str, Any]) -> WeatherAlert | None:
        alert_type = _clean_value(
            item.get("typeName") or item.get("eventType")
        ) or _parse_alert_type(_clean_value(item.get("title")))
        if not alert_type:
            return None
        level = normalize_level(
            item.get("level") or item.get("severity") or item.get("grade")
        )
        title = _clean_value(item.get("title")) or alert_type + "预警"
        description = _clean_value(item.get("text")) or title
        alert_id = str(item.get("id") or item.get("alertid") or title)
        return WeatherAlert(
            alert_id=alert_id,
            location=location,
            alert_type=alert_type,
            level=level,
            title=title,
            description=description,
            safety_guidance=_clean_value(item.get("instruction")),
            status="active",
            published_at=_parse_datetime(
                item.get("publishedTime")
                or item.get("publishTime")
                or item.get("pubTime")
            ),
            started_at=_parse_datetime(item.get("effectiveTime")),
            ended_at=_parse_datetime(item.get("expireTime")),
            source=SOURCE_QWEATHER,
            source_url=_clean_value(item.get("url"))
            or "https://dev.qweather.com/",
            raw=dict(item),
        )

    @staticmethod
    def _json_response(response: httpx.Response) -> dict[str, Any]:
        try:
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise DataSourceError(f"和风天气响应解析失败: {exc}") from exc
        if not isinstance(payload, dict):
            raise DataSourceError("和风天气响应不是 JSON 对象")
        return payload


_ALERT_TYPES = [
    "台风",
    "暴雨",
    "暴雪",
    "雷雨大风",
    "道路结冰",
    "强对流",
    "寒潮",
    "高温",
    "低温",
    "大风",
    "雷电",
    "冰雹",
    "大雾",
    "雾",
    "沙尘暴",
    "霾",
    "霜冻",
    "山洪",
    "地质灾害",
    "其它",
]


def normalize_level(value: Any) -> str:
    text = _clean_value(value).lower()
    aliases = {
        "blue": "蓝色",
        "yellow": "黄色",
        "orange": "橙色",
        "red": "红色",
        "minor": "蓝色",
        "moderate": "黄色",
        "severe": "橙色",
        "extreme": "红色",
        "un": "未知",
        "unknown": "未知",
    }
    if text in aliases:
        return aliases[text]
    if text in {"蓝", "蓝色"}:
        return "蓝色"
    if text in {"黄", "黄色"}:
        return "黄色"
    if text in {"橙", "橙色"}:
        return "橙色"
    if text in {"红", "红色"}:
        return "红色"
    for color, label in (
        ("蓝色", "蓝色"),
        ("黄色", "黄色"),
        ("橙色", "橙色"),
        ("红色", "红色"),
    ):
        if color in text:
            return label
    return "未知"


def level_rank(level: str) -> int:
    return LEVEL_RANK.get(normalize_level(level), 0)


def matches_alert_type(alert_type: str, configured: list[str]) -> bool:
    if not configured:
        return True
    normalized = _clean_value(alert_type)
    return any(
        item in normalized
        or normalized in item
        for item in configured
        if item.strip()
    )


def _normalize_name(value: str) -> str:
    text = re.sub(r"\s+", "", value or "")
    suffixes = [
        "维吾尔自治区",
        "壮族自治区",
        "回族自治区",
        "特别行政区",
        "自治区",
        "自治州",
        "自治县",
        "地区",
        "盟",
        "省",
        "市",
        "县",
        "区",
    ]
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)]
                changed = True
    return text


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in {"", "-", "9999", "9999.0", "null", "None"}
    if isinstance(value, (int, float)):
        return value in (9999, 9999.0)
    return False


def _clean_value(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip()


def _absolute_url(value: str) -> str:
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("/"):
        return NMC_BASE_URL + value
    return value


def _alert_id_from_url(value: str) -> str:
    match = _ALERT_ID_RE.search(value or "")
    return match.group(1) if match else ""


def _alert_time_from_url(value: str) -> datetime | None:
    match = _URL_ALERT_TIME_RE.search(value or "")
    if not match:
        return None
    try:
        return datetime.strptime(
            match.group(1),
            "%Y%m%d%H%M%S",
        ).replace(tzinfo=CN_TZ)
    except ValueError:
        return None


def _parse_chinese_time(value: str) -> datetime | None:
    match = _CHINESE_TIME_RE.search(value or "")
    if not match:
        return None
    year, month, day, hour, minute = (
        int(part) for part in match.groups()
    )
    try:
        return datetime(
            year,
            month,
            day,
            hour,
            minute,
            tzinfo=CN_TZ,
        )
    except ValueError:
        return None


def _parse_nmc_issue_time(value: Any) -> datetime | None:
    text = _clean_value(value)
    if not text:
        return None
    for fmt in ("%Y/%m/%d %H:%M", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=CN_TZ)
        except ValueError:
            continue
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=CN_TZ)
    text = _clean_value(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=CN_TZ)


def _parse_alarm_html(value: str) -> tuple[str, str]:
    blocks = []
    for raw in re.findall(
        r'<div\s+id\s*=\s*["\']?alarmtext["\']?[^>]*>(.*?)</div>',
        value or "",
        flags=re.IGNORECASE | re.DOTALL,
    ):
        text = re.sub(r"<[^>]+>", "\n", raw)
        text = html.unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n", text).strip()
        if text:
            blocks.append(text)
    description = blocks[0] if blocks else ""
    safety = blocks[1] if len(blocks) > 1 else ""
    return description, safety


def _default_warning_safety(alert_type: str) -> str:
    tips = {
        "台风": "请停止户外活动，远离海边、临时建筑和广告牌，服从当地应急安排。",
        "暴雨": "避免进入低洼地区、涵洞和地下空间，防范山洪、滑坡和城市内涝。",
        "高温": "减少午后户外活动，及时补水，关注老人与儿童防暑降温。",
        "寒潮": "注意添衣保暖，防范道路结冰和大风降温对交通的影响。",
        "大风": "加固门窗、围板、广告牌等易被吹动的物品，避免高空作业。",
        "雷电": "远离空旷地带、大树、金属构筑物和水面，停止户外活动。",
        "大雾": "减少不必要出行，驾车保持车距并开启雾灯。",
    }
    return tips.get(
        alert_type,
        "请密切关注气象部门最新预警信息，避免进入危险区域，服从当地应急安排。",
    )


def _parse_alert_type(value: str) -> str:
    text = _clean_value(value)
    for alert_type in _ALERT_TYPES:
        if alert_type in text:
            if alert_type == "雾" and "大雾" not in text:
                continue
            return alert_type
    return "其它"
