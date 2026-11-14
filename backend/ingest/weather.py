"""Local weather for data/weather.json: forecast from Open-Meteo plus active alerts from the National Weather Service.

Both are free and keyless. The forecast is required; alerts fail soft (`alerts_ok` says whether they could be read),
because a missing alert list must not hide the forecast, and the page can say "alerts unavailable"."""

import json
import math
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from ingest.feeds import FeedError, clean_text, fetch

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
NWS_ALERTS = "https://api.weather.gov/alerts/active"
JSON_ACCEPT = "application/geo+json, application/json"
WEATHER_USER_AGENT = "NewsPWA/1.0 (personal weather reader)"  # NWS asks API clients to identify themselves
WAIT_SECONDS = 8  # a hard cap on each answer; the socket timeout alone can run longer than the fetch deadline
DEADLINE_SECONDS = 6
HOURS = 24
DAYS = 7
MAX_ALERTS = 10
SEVERITIES = {"Extreme", "Severe", "Moderate", "Minor", "Unknown"}

_CURRENT = "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,wind_gusts_10m,is_day"
_HOURLY = "temperature_2m,precipitation_probability,weather_code"
_DAILY = "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset"


class WeatherError(Exception):
    """The forecast could not be fetched or did not look like a forecast."""


def _num(value: Any) -> float | None:
    """A finite number, or None (JSON gives null for gaps, and a bad value must not reach the page)."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return round(float(value), 1)


def _series(block: Any, key: str, count: int) -> list[Any]:
    values = block.get(key) if isinstance(block, dict) else None
    if not isinstance(values, list):
        raise WeatherError(f"forecast is missing {key}")
    return values[:count]


def forecast_url(lat: float, lon: float) -> str:
    query = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "current": _CURRENT,
        "hourly": _HOURLY,
        "daily": _DAILY,
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": "auto",
        "forecast_days": DAYS,
        "forecast_hours": HOURS,
    }
    return f"{OPEN_METEO}?{urlencode(query, safe=',')}"


def parse_forecast(body: bytes) -> dict[str, Any]:
    """Open-Meteo JSON -> {"current", "hourly": [...24], "daily": [...7]}. Times are local, as Open-Meteo returns them."""
    try:
        doc = json.loads(body)
        cur = doc["current"]
        hourly, daily = doc["hourly"], doc["daily"]
        hour_times = [str(t) for t in _series(hourly, "time", HOURS)]
        day_times = [str(t) for t in _series(daily, "time", DAYS)]
        cols = {k: _series(hourly, k, HOURS) for k in ("temperature_2m", "precipitation_probability", "weather_code")}
        dcols = {
            k: _series(daily, k, DAYS)
            for k in (
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_probability_max",
                "sunrise",
                "sunset",
            )
        }
        current = {
            "time": str(cur["time"]),
            "temp": _num(cur.get("temperature_2m")),
            "feels_like": _num(cur.get("apparent_temperature")),
            "humidity": _num(cur.get("relative_humidity_2m")),
            "code": _num(cur.get("weather_code")),
            "wind": _num(cur.get("wind_speed_10m")),
            "gust": _num(cur.get("wind_gusts_10m")),
            "is_day": bool(cur["is_day"]) if cur.get("is_day") in (0, 1) else None,
        }
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise WeatherError(f"forecast is not usable: {type(exc).__name__}") from exc
    if current["temp"] is None or not hour_times or not day_times:
        raise WeatherError("forecast has no current temperature or no hours or days")

    def at(values: list[Any], i: int) -> Any:
        return values[i] if i < len(values) else None

    return {
        "current": current,
        "hourly": [
            {
                "time": t,
                "temp": _num(at(cols["temperature_2m"], i)),
                "pop": _num(at(cols["precipitation_probability"], i)),
                "code": _num(at(cols["weather_code"], i)),
            }
            for i, t in enumerate(hour_times)
        ],
        "daily": [
            {
                "date": t,
                "code": _num(at(dcols["weather_code"], i)),
                "high": _num(at(dcols["temperature_2m_max"], i)),
                "low": _num(at(dcols["temperature_2m_min"], i)),
                "pop": _num(at(dcols["precipitation_probability_max"], i)),
                "sunrise": str(at(dcols["sunrise"], i) or ""),
                "sunset": str(at(dcols["sunset"], i) or ""),
            }
            for i, t in enumerate(day_times)
        ],
    }


def parse_alerts(body: bytes) -> list[dict[str, Any]]:
    """NWS alerts GeoJSON -> a short list, most severe first. Text is plain text (it is shown, never rendered as HTML)."""
    try:
        features = json.loads(body)["features"]
        alerts = []
        for feature in features:
            try:  # one malformed alert is skipped; the others are still shown
                p = feature["properties"]
                severity = p.get("severity") if p.get("severity") in SEVERITIES else "Unknown"
                alerts.append(
                    {
                        "id": str(p["id"]),
                        "event": clean_text(p.get("event"), 80),
                        "severity": severity,
                        "headline": clean_text(p.get("headline"), 200),
                        "instruction": clean_text(p.get("instruction"), 300),
                        "ends": str(p.get("ends") or p.get("expires") or ""),
                    }
                )
            except KeyError, TypeError, AttributeError:
                continue
    except (ValueError, KeyError, TypeError) as exc:
        raise WeatherError(f"alerts are not usable: {type(exc).__name__}") from exc
    order = ["Extreme", "Severe", "Moderate", "Minor", "Unknown"]
    alerts.sort(key=lambda a: order.index(a["severity"]))
    return alerts[:MAX_ALERTS]


def build_weather(lat: float, lon: float, *, getter: Any = None, now: datetime | None = None) -> dict[str, Any]:
    """The weather document. Raises WeatherError if the forecast is unavailable; alerts failing only sets alerts_ok false."""
    get = getter or (lambda url: fetch(url, accept=JSON_ACCEPT, deadline_seconds=DEADLINE_SECONDS, user_agent=WEATHER_USER_AGENT))
    alerts_url = f"{NWS_ALERTS}?{urlencode({'point': f'{lat:.4f},{lon:.4f}'}, safe=',')}"
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        forecast_future = pool.submit(get, forecast_url(lat, lon))
        alerts_future = pool.submit(get, alerts_url)
        try:
            forecast = parse_forecast(forecast_future.result(timeout=WAIT_SECONDS))
        except (FeedError, FutureTimeout) as exc:
            raise WeatherError(str(exc) or "forecast timed out") from exc
        try:
            alerts, alerts_ok = parse_alerts(alerts_future.result(timeout=WAIT_SECONDS)), True
        except FeedError, WeatherError, FutureTimeout:
            alerts, alerts_ok = [], False
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # a stalled request is abandoned, not waited for
    generated = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    return {"generated": generated, **forecast, "alerts": alerts, "alerts_ok": alerts_ok}
