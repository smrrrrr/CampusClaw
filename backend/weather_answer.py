"""天气是结构化事实，直接格式化，避免资料提示词干扰和单位 LaTeX。"""
import json

WEATHER_CODES = {0: "晴", 1: "少云", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇", 51: "小毛毛雨", 53: "毛毛雨", 55: "强毛毛雨", 56: "冻毛毛雨", 57: "强冻毛毛雨", 61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "强冻雨", 71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒", 80: "阵雨", 81: "较强阵雨", 82: "强阵雨", 85: "阵雪", 86: "强阵雪", 95: "雷暴", 96: "雷暴伴冰雹", 99: "强雷暴伴冰雹"}


def weather_answer(results: list[dict]) -> str | None:
    if not results or not all(r["tool_ref"].startswith("weather_query@") for r in results):
        return None
    lines = []
    for result in results:
        if result["status"] != "ok":
            lines.append(result["text"] if result["status"] != "denied" else "天气查询工具当前未连接，请联系老师重新连接后再试。")
            continue
        try:
            data = json.loads(result["text"])
            place = data["location"]
            actual = "、".join(dict.fromkeys(str(place[k]) for k in ("name", "admin2", "admin1", "country") if place.get(k)))
            requested = place.get("requested") or place["name"]
            lines.append(f"**{requested}天气**\n\n匹配地点：{actual}。时区：{data['timezone']}。")
            current = data.get("current") or {}
            if current:
                parts = []
                if current.get("temperature_2m") is not None: parts.append(f"气温 {current['temperature_2m']:g}°C")
                if current.get("relative_humidity_2m") is not None: parts.append(f"相对湿度 {current['relative_humidity_2m']:g}%")
                if current.get("wind_speed_10m") is not None: parts.append(f"风速 {current['wind_speed_10m']:g} km/h")
                code = current.get("weather_code")
                if code is not None: parts.append(WEATHER_CODES.get(code, f"天气代码 {code}"))
                lines.append(f"当前（{current.get('time', '时间未提供')}）：" + "，".join(parts) + "。")
            for day in data["forecast"]:
                pieces = []
                code = day.get("weather_code")
                if code is not None: pieces.append(WEATHER_CODES.get(code, f"天气代码 {code}"))
                low, high = day.get("temperature_2m_min"), day.get("temperature_2m_max")
                if low is not None and high is not None: pieces.append(f"{low:g}–{high:g}°C")
                if day.get("precipitation_probability_max") is not None: pieces.append(f"最大降水概率 {day['precipitation_probability_max']:g}%")
                lines.append(f"- {day['time']}：" + "，".join(pieces) + "。")
            lines.append(f"\n来源：[Open-Meteo](https://open-meteo.com/)，数值天气模型；获取时间 {data['fetched_at']}。")
            if data.get("precision_note"): lines.append(data["precision_note"])
        except (ValueError, KeyError, TypeError):
            lines.append("天气工具返回的数据格式异常，请稍后重试。")
    return "\n\n".join(lines)
