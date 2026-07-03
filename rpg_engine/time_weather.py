from __future__ import annotations

import re


PERIOD_PATTERNS = [
    ("dawn", "清晨", ("清晨", "黎明", "天亮", "早上", "拂晓")),
    ("morning", "上午", ("上午", "早饭后")),
    ("noon", "中午", ("中午", "正午", "午间")),
    ("afternoon", "下午", ("下午", "午后")),
    ("evening", "傍晚", ("傍晚", "黄昏", "日落")),
    ("night", "入夜", ("入夜", "夜间", "夜里", "晚上", "天黑")),
]


def enrich_time_weather_meta(meta: dict[str, str]) -> dict[str, str]:
    result = dict(meta)
    time_block = result.get("current_time_block")
    if time_block:
        for key, value in parse_time_block(time_block).items():
            result.setdefault(key, value)

    weather_label = result.get("weather_label")
    if weather_label:
        for key, value in parse_weather_label(weather_label, result).items():
            result.setdefault(key, value)
    return result


def parse_time_block(value: str) -> dict[str, str]:
    text = value.strip()
    display_text = text.split("→")[-1].strip()
    day_matches = re.findall(r"第\s*(\d+)\s*天", display_text or text)
    display_text = re.sub(r"^第\s*\d+\s*天\s*[·\s-]*", "", display_text).strip()
    label, note = split_label_note(display_text or text)
    period, default_label = infer_period(display_text or text)
    result = {
        "current_period": period,
        "current_period_label": label or default_label,
        "current_time_note": note,
    }
    if day_matches:
        result["current_game_day"] = day_matches[-1]
    return result


def parse_weather_label(value: str, meta: dict[str, str] | None = None) -> dict[str, str]:
    text = value.strip()
    label, note = split_label_note(text)
    condition, condition_label = infer_weather_condition(text)
    precipitation = infer_precipitation(text, condition)
    result = {
        "weather_condition": condition,
        "weather_condition_label": label or condition_label,
        "weather_precipitation": precipitation,
        "weather_temperature": infer_temperature(text, meta or {}),
        "weather_wind": infer_wind(text),
        "weather_note": note,
    }
    if "干旱" in text:
        result["drought_state"] = "active"
    if "地表水全断" in text:
        result["water_pressure"] = "severe"
    elif "水量下降" in text or "缺水" in text:
        result["water_pressure"] = "stressed"
    return result


def split_label_note(value: str) -> tuple[str, str]:
    text = value.strip()
    if not text:
        return "", ""
    match = re.match(r"^([^（(]+)[（(](.*)[）)]$", text)
    if match:
        return match.group(1).strip(" ，,、"), match.group(2).strip()
    parts = re.split(r"[，,；;]", text, maxsplit=1)
    label = parts[0].strip()
    note = parts[1].strip() if len(parts) > 1 else ""
    return label, note


def infer_period(text: str) -> tuple[str, str]:
    for period, label, patterns in PERIOD_PATTERNS:
        if any(pattern in text for pattern in patterns):
            return period, label
    return "unknown", text.strip() or "未知"


def infer_weather_condition(text: str) -> tuple[str, str]:
    lowered = text.lower()
    if "暴雨" in text or "雷雨" in text or "storm" in lowered:
        return "storm", "暴雨"
    if "雨" in text or "rain" in lowered:
        return "rain", "雨"
    if "雾" in text or "fog" in lowered:
        return "fog", "雾"
    if "雪" in text or "snow" in lowered:
        return "snow", "雪"
    if "阴" in text or "overcast" in lowered:
        return "overcast", "阴"
    if "云" in text or "cloud" in lowered:
        return "cloudy", "多云"
    if "晴" in text or "clear" in lowered:
        return "clear", "晴"
    return "unknown", text.strip() or "未知"


def infer_precipitation(text: str, condition: str) -> str:
    if "暴雨" in text or "大雨" in text or condition == "storm":
        return "heavy"
    if "中雨" in text:
        return "moderate"
    if "小雨" in text or "细雨" in text or "毛毛雨" in text:
        return "light"
    if condition in {"rain", "snow"}:
        return "present"
    if condition in {"clear", "cloudy", "overcast", "fog"} or "干旱" in text:
        return "none"
    return "unknown"


def infer_temperature(text: str, meta: dict[str, str]) -> str:
    if any(word in text for word in ("炎热", "酷热", "很热")):
        return "hot"
    if "热" in text:
        return "warm"
    if any(word in text for word in ("寒冷", "很冷", "严寒")):
        return "cold"
    if "冷" in text or "微凉" in text or "凉" in text:
        return "cool"
    if "温暖" in text or "暖" in text:
        return "mild"
    season = meta.get("season_label", "")
    if "晚春" in season or "春" in season:
        return "mild"
    return "unknown"


def infer_wind(text: str) -> str:
    if "大风" in text or "强风" in text:
        return "strong"
    if "风" in text:
        if "无风" in text or "风静" in text:
            return "calm"
        if "微风" in text:
            return "light"
        return "present"
    return "unrecorded"


def format_time_brief(meta: dict[str, str]) -> str:
    day = meta.get("current_game_day", "?")
    label = meta.get("current_period_label") or meta.get("current_time_block", "未知")
    note = meta.get("current_time_note", "")
    return f"第{day}天 · {label}{f'（{note}）' if note else ''}"


def format_weather_brief(meta: dict[str, str]) -> str:
    label = meta.get("weather_label")
    if label:
        return label
    condition = meta.get("weather_condition_label") or meta.get("weather_condition") or "未登记"
    temperature = meta.get("weather_temperature")
    precipitation = meta.get("weather_precipitation")
    parts = [condition]
    if temperature and temperature != "unknown":
        parts.append(f"temperature={temperature}")
    if precipitation and precipitation != "unknown":
        parts.append(f"precipitation={precipitation}")
    return "；".join(parts)
