"""Shared message rendering for push channels."""

from assistant.models import ContentBlock, ContentItem, Report


def render_push_markdown(
    report: Report,
    max_items: int = 5,
    max_bytes: int | None = None,
) -> str:
    """Render a compact Markdown report suitable for WeChat push channels."""

    parts = [
        f"# {report.title}",
        f"生成时间：{report.generated_at:%Y-%m-%d %H:%M}",
        f"地区：{report.location}",
    ]
    if report.degraded:
        parts.append("> 部分数据源降级，内容可能不完整。")

    for block in report.blocks:
        parts.append(_render_block(block, max_items=max_items))

    text = "\n\n".join(parts)
    if max_bytes is not None:
        return _fit_bytes(text, max_bytes)
    return text


def _render_block(block: ContentBlock, max_items: int) -> str:
    lines = [f"## {block.title}"]
    if block.status == "failed":
        lines.append(f"- 数据不可用：{block.message or '无详细信息'}")
        return "\n".join(lines)

    if block.kind == "weather":
        lines.extend(_render_weather(block))
        return "\n".join(lines)

    items = block.items[:max_items]
    if not items:
        lines.append("- 暂无内容")
        return "\n".join(lines)

    for item in items:
        lines.append(_render_item(item))
    return "\n".join(lines)


def _render_weather(block: ContentBlock) -> list[str]:
    lines: list[str] = []
    current = block.details.get("current", {})
    if current:
        description = current.get("description") or "未知"
        temperature = current.get("temperature")
        if temperature is not None:
            lines.append(f"- 当前：{description}，{_num(temperature)}°C")
        else:
            lines.append(f"- 当前：{description}")
        if current.get("apparent_temperature") is not None:
            lines.append(f"- 体感：{_num(current['apparent_temperature'])}°C")
        if current.get("humidity") is not None:
            lines.append(f"- 湿度：{_num(current['humidity'])}%")
        if current.get("precipitation_probability") is not None:
            lines.append(
                f"- 降水概率：{_num(current['precipitation_probability'])}%"
            )
        if current.get("air_quality_aqi") is not None:
            lines.append(f"- 空气质量 AQI：{_num(current['air_quality_aqi'])}")
        if current.get("pm2_5") is not None:
            lines.append(f"- PM2.5：{_num(current['pm2_5'])}")
    else:
        lines.append("- 暂无实时天气数据")

    days = block.details.get("days", [])
    if len(days) > 1:
        day = days[1]
        lines.append(
            f"- 明日：{day.get('description', '未知')}，"
            f"{_num(day.get('temp_min'))}~{_num(day.get('temp_max'))}°C"
        )
    return lines


def _render_item(item: ContentItem) -> str:
    label = item.title
    if item.url:
        line = f"- [{label}]({item.url})"
    else:
        line = f"- {label}"
    details: list[str] = []
    if item.stars is not None:
        details.append(f"⭐{_num(item.stars)}")
    elif item.language:
        details.append(item.language)
    if item.source:
        details.append(item.source)
    if details:
        line += f"（{' · '.join(details)}）"
    return line


def _num(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _fit_bytes(text: str, max_bytes: int) -> str:
    """Truncate text to a UTF-8 byte budget without splitting a character."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    encoded = encoded[:max_bytes]
    while encoded:
        try:
            return encoded.decode("utf-8")
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    return ""