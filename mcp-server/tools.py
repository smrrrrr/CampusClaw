"""只读教学工具：固定公式、量纲换算与真实 Open-Meteo 天气。"""
import asyncio
import json
import math
import re
import time
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FormulaArgs(Arguments):
    topic: str = Field(min_length=1, max_length=500)


class ConvertArgs(Arguments):
    value: FiniteFloat
    from_unit: str = Field(min_length=1, max_length=20)
    to_unit: str = Field(min_length=1, max_length=20)


class WeatherArgs(Arguments):
    location: str = Field(min_length=2, max_length=80)
    days: int = Field(default=1, ge=1, le=7)
    day_offset: int = Field(default=0, ge=0, le=6)

    @model_validator(mode="after")
    def check_window(self):
        if self.days + self.day_offset > 7:
            raise ValueError("只能查询未来七天内的天气")
        return self


FORMULAS = [
    (("二次", "求根"), "一元二次方程", "ax²+bx+c=0；Δ=b²−4ac；x=(−b±√Δ)/(2a)。条件：a≠0；实数解要求 Δ≥0。先整理标准形式，再计算判别式，最后代入并验根。"),
    (("勾股", "直角三角"), "勾股定理", "a²+b²=c²。条件：直角三角形，c 为斜边。先确认直角和斜边，再代入已知边长；不能用于一般三角形。"),
    (("速度", "路程", "速率"), "平均速度/速率", "平均速率 v=s/t（总路程/总时间，t>0）；平均速度为位移/时间，具有方向。SI 单位 m/s。先区分路程与位移，并统一单位。"),
    (("密度", "质量", "体积"), "密度", "ρ=m/V（V>0），m=ρV，V=m/ρ（ρ>0）。SI 单位 kg/m³。先统一质量和体积单位，再代入；留意 g/cm³ 与 kg/m³。"),
    (("牛顿", "加速度", "合力"), "牛顿第二定律", "合外力 F=ma。条件：惯性参考系、质量恒定的经典力学问题。先画受力图，求合外力，再按方向列分量方程。SI 单位 N=kg·m/s²。"),
    (("欧姆", "电阻", "电流", "电压"), "欧姆定律", "U=IR，I=U/R（R>0）。条件：温度等条件不变的欧姆导体。先确定同一段电路的 U/I/R，统一 V/A/Ω 后代入。"),
]


def formula_hint(args: FormulaArgs) -> str:
    matches = [f"{title}：{text}" for words, title, text in FORMULAS if any(w in args.topic for w in words)]
    return "\n\n".join(matches) if matches else "公式库暂未覆盖该主题。支持：一元二次方程、勾股定理、速度、密度、牛顿第二定律、欧姆定律。请明确知识点。"


# dimension, scale to SI; temperatures are handled separately with offsets.
UNITS = {}
for dimension, entries in {
    "length": {"mm": .001, "cm": .01, "m": 1, "km": 1000},
    "area": {"mm2": .000001, "cm2": .0001, "m2": 1, "km2": 1000000},
    "volume": {"ml": .000001, "cm3": .000001, "l": .001, "m3": 1},
    "mass": {"mg": .000001, "g": .001, "kg": 1, "t": 1000},
    "time": {"s": 1, "min": 60, "h": 3600},
    "speed": {"m/s": 1, "km/h": 1 / 3.6},
}.items():
    UNITS.update({unit: (dimension, scale) for unit, scale in entries.items()})
ALIASES = {
    "毫米": "mm", "厘米": "cm", "米": "m", "千米": "km", "公里": "km",
    "平方毫米": "mm2", "平方厘米": "cm2", "平方米": "m2", "平方千米": "km2",
    "毫升": "ml", "立方厘米": "cm3", "升": "l", "立方米": "m3",
    "毫克": "mg", "克": "g", "千克": "kg", "公斤": "kg", "吨": "t",
    "秒": "s", "分钟": "min", "小时": "h", "米/秒": "m/s", "千米/小时": "km/h", "公里/小时": "km/h",
    "摄氏度": "c", "°c": "c", "℃": "c", "华氏度": "f", "°f": "f", "℉": "f", "开尔文": "k",
}


def normalize_unit(value: str) -> str:
    value = value.strip().lower().replace("²", "2").replace("³", "3").replace("^", "")
    return ALIASES.get(value, value)


def unit_convert(args: ConvertArgs) -> str:
    source, target = normalize_unit(args.from_unit), normalize_unit(args.to_unit)
    if source in {"c", "f", "k"} and target in {"c", "f", "k"}:
        kelvin = {"c": lambda x: x + 273.15, "f": lambda x: (x - 32) * 5 / 9 + 273.15, "k": lambda x: x}[source](args.value)
        if kelvin < -1e-9:
            raise ValueError("温度不能低于绝对零度")
        result = {"c": lambda x: x - 273.15, "f": lambda x: (x - 273.15) * 9 / 5 + 32, "k": lambda x: x}[target](max(0, kelvin))
    else:
        if source not in UNITS or target not in UNITS:
            raise ValueError("不支持该单位，请使用长度、面积、体积、质量、时间、速度或温度单位")
        if UNITS[source][0] != UNITS[target][0]:
            raise ValueError("不能在不同量纲之间换算")
        result = args.value * UNITS[source][1] / UNITS[target][1]
    if not math.isfinite(result):
        raise ValueError("换算结果超出数值范围")
    return f"{args.value:g} {args.from_unit} = {result:.12g} {args.to_unit}"


CITY_NAMES = {"北京": "Beijing", "上海": "Shanghai", "广州": "Guangzhou", "深圳": "Shenzhen", "杭州": "Hangzhou", "南京": "Nanjing", "成都": "Chengdu", "武汉": "Wuhan", "西安": "Xi'an", "天津": "Tianjin", "重庆": "Chongqing"}
_weather_cache: dict[tuple, tuple[float, str]] = {}
_geocoding_cache: dict[str, tuple[float, dict]] = {}


def _admin_key(value: str) -> str:
    value = re.sub(r"(?:壮族自治区|回族自治区|维吾尔自治区|特别行政区|自治区|省|市|区|县)$", "", value.strip())
    return next((cn for cn, en in CITY_NAMES.items() if value.casefold() == en.casefold()), value)


async def resolve_location(client: httpx.AsyncClient, requested: str) -> dict:
    cached = _geocoding_cache.get(requested)
    if cached and time.monotonic() - cached[0] < 86400:
        return cached[1]
    parts = re.findall(r".+?(?:自治区|省|市)|.+$", requested)
    parents, locality = (parts[:-1], parts[-1]) if len(parts) > 1 else ([], requested)
    if not parents:
        for city in ("北京", "上海", "天津", "重庆"):
            if locality.startswith(city) and locality != city:
                parents, locality = [city], locality[len(city):]
                break
    district = bool(parents) or locality.endswith(("区", "县"))
    short = re.sub(r"[市区县]$", "", locality)
    queries = list(dict.fromkeys([CITY_NAMES.get(requested.removesuffix("市"), requested), CITY_NAMES.get(short, short)]))
    matches = []
    for query in queries[:2]:
        response = await client.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": query, "count": 10, "language": "zh", "format": "json"})
        response.raise_for_status()
        places = response.json().get("results") or []
        for place in places:
            labels = [_admin_key(str(place.get(k, ""))) for k in ("name", "admin1", "admin2", "admin3", "admin4")]
            if any(_admin_key(parent) not in labels for parent in parents):
                continue
            if district and _admin_key(str(place.get("name", ""))) != _admin_key(locality):
                continue
            if not any(p.get("id", (p["latitude"], p["longitude"])) == place.get("id", (place["latitude"], place["longitude"])) for p in matches):
                matches.append(place)
        if matches:
            break
    if not matches:
        raise ValueError("未找到该地点，请提供城市和区县名称，例如“北京市大兴区”；不会用市中心天气冒充区县结果。")
    if district and len(matches) > 1:
        choices = "、".join("/".join(str(p.get(k, "")) for k in ("name", "admin2", "admin1")) for p in matches[:3])
        raise ValueError(f"找到多个同名地点（{choices}），请补充所属城市或省份。")
    place = {**matches[0], "requested": requested}
    if len(_geocoding_cache) >= 128:
        _geocoding_cache.pop(next(iter(_geocoding_cache)))
    _geocoding_cache[requested] = (time.monotonic(), place)
    return place


async def weather_query(args: WeatherArgs) -> str:
    key = (args.location.strip(), args.days, args.day_offset)
    cached = _weather_cache.get(key)
    if cached and time.monotonic() - cached[0] < 300:
        return cached[1]
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False) as client:
            place = await resolve_location(client, args.location.strip())
            response = await client.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto",
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
                "forecast_days": args.days + args.day_offset,
            })
            response.raise_for_status()
            data = response.json()
            daily = data["daily"]
            days = [{field: values[i] for field, values in daily.items()} for i in range(args.day_offset, args.day_offset + args.days)]
            result = json.dumps({
                "location": {k: place.get(k) for k in ("requested", "name", "admin1", "admin2", "country", "latitude", "longitude")},
                "precision_note": "按匹配地点附近的气象模型网格提供预报，并非街道或小区的实时实测。",
                "timezone": data["timezone"], "current": data.get("current"), "current_units": data.get("current_units"),
                "forecast": days, "daily_units": data.get("daily_units"),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "source": "Open-Meteo 数值天气模型（非气象站实时观测）",
                "source_url": "https://open-meteo.com/", "weather_codes": "https://open-meteo.com/en/docs#weathervariables",
            }, ensure_ascii=False, allow_nan=False)
    except (httpx.HTTPError, KeyError, TypeError, IndexError, json.JSONDecodeError) as exc:
        raise ValueError("天气服务暂不可用，请稍后重试") from exc
    if len(_weather_cache) >= 128:
        _weather_cache.pop(next(iter(_weather_cache)))
    _weather_cache[key] = (time.monotonic(), result)
    return result


TOOLS = {
    "formula_hint": (FormulaArgs, formula_hint, "查询数学/物理公式、条件与解题提示"),
    "unit_convert": (ConvertArgs, unit_convert, "长度、面积、体积、质量、时间、速度和温度换算"),
    "weather_query": (WeatherArgs, weather_query, "按城市或区县查询当前天气及未来七天内预报，含匹配地点、时间与来源；同名地点需注明所属市/省"),
}


def list_tools() -> list[dict]:
    return [{"name": name, "description": description, "inputSchema": model.model_json_schema(), "annotations": {"readOnlyHint": True, "destructiveHint": False}} for name, (model, _, description) in TOOLS.items()]


async def call_tool(name: str, arguments: dict) -> dict:
    if name not in TOOLS:
        raise KeyError(name)
    model, function, _ = TOOLS[name]
    try:
        args = model.model_validate(arguments)
        text = await function(args) if asyncio.iscoroutinefunction(function) else function(args)
        return {"content": [{"type": "text", "text": text}], "isError": False}
    except ValueError as exc:
        # Pydantic errors include only caller-provided values, no credentials.
        return {"content": [{"type": "text", "text": str(exc)[:1200]}], "isError": True}
