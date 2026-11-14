import json
from datetime import UTC, datetime
from typing import Any

import pytest

from ingest import weather
from ingest.feeds import FeedError
from ingest.weather import WeatherError, build_weather, forecast_url, parse_alerts, parse_forecast

LAT, LON = 40.0, -90.0
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def forecast_doc(**over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "current": {
            "time": "2026-11-13T06:00",
            "temperature_2m": 41.04,
            "apparent_temperature": 35.0,
            "relative_humidity_2m": 60,
            "weather_code": 61,
            "wind_speed_10m": 8.2,
            "wind_gusts_10m": 19.0,
            "is_day": 1,
        },
        "hourly": {
            "time": [f"2026-11-13T{h:02d}:00" for h in range(24)],
            "temperature_2m": [40.0 + h for h in range(24)],
            "precipitation_probability": [10] * 24,
            "weather_code": [3] * 24,
        },
        "daily": {
            "time": [f"2026-11-{13 + d}" for d in range(7)],
            "weather_code": [61] * 7,
            "temperature_2m_max": [46.0] * 7,
            "temperature_2m_min": [34.0] * 7,
            "precipitation_probability_max": [70] * 7,
            "sunrise": ["2026-11-13T06:39"] * 7,
            "sunset": ["2026-11-13T16:32"] * 7,
        },
    }
    doc.update(over)
    return doc


def alert(id_: str, severity: Any, **props: Any) -> dict[str, Any]:
    return {"properties": {"id": id_, "event": f"Event {id_}", "severity": severity, "headline": "<b>Head</b>line", **props}}


def alerts_doc(*features: dict[str, Any]) -> bytes:
    return json.dumps({"features": list(features)}).encode()


def test_forecast_url_has_the_point_and_units() -> None:
    url = forecast_url(LAT, LON)
    assert url.startswith("https://api.open-meteo.com/v1/forecast?")
    assert "latitude=40.0000" in url and "longitude=-90.0000" in url
    assert "temperature_unit=fahrenheit" in url and "wind_speed_unit=mph" in url


def test_parse_forecast_shapes_the_document() -> None:
    w = parse_forecast(json.dumps(forecast_doc()).encode())
    assert w["current"] == {
        "time": "2026-11-13T06:00",
        "temp": 41.0,
        "feels_like": 35.0,
        "humidity": 60.0,
        "code": 61.0,
        "wind": 8.2,
        "gust": 19.0,
        "is_day": True,
    }
    assert len(w["hourly"]) == 24 and w["hourly"][1] == {"time": "2026-11-13T01:00", "temp": 41.0, "pop": 10.0, "code": 3.0}
    assert len(w["daily"]) == 7 and w["daily"][0]["high"] == 46.0 and w["daily"][0]["sunset"] == "2026-11-13T16:32"


def test_parse_forecast_keeps_nulls_as_none_and_pads_short_series() -> None:
    doc = forecast_doc()
    doc["hourly"]["temperature_2m"] = [None, True, "warm"]
    doc["hourly"]["time"] = doc["hourly"]["time"][:4]
    doc["daily"]["sunrise"] = [None]
    doc["current"]["wind_gusts_10m"] = None
    w = parse_forecast(json.dumps(doc).encode())
    assert [h["temp"] for h in w["hourly"]] == [None, None, None, None]
    assert w["current"]["gust"] is None
    assert w["daily"][0]["sunrise"] == "" and w["daily"][3]["sunrise"] == ""


def test_parse_forecast_truncates_to_24_hours_and_7_days() -> None:
    doc = forecast_doc()
    doc["hourly"]["time"] = [f"t{i}" for i in range(48)]
    doc["daily"]["time"] = [f"d{i}" for i in range(10)]
    w = parse_forecast(json.dumps(doc).encode())
    assert len(w["hourly"]) == 24 and len(w["daily"]) == 7


def test_parse_forecast_drops_non_finite_numbers() -> None:
    # Python's json accepts NaN/Infinity literals; they must not reach the page (which would break JSON.parse).
    doc = json.dumps(forecast_doc()).replace('"wind_gusts_10m": 19.0', '"wind_gusts_10m": NaN')
    assert parse_forecast(doc.encode())["current"]["gust"] is None


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b"{}",
        json.dumps({**forecast_doc(), "hourly": {"time": []}}).encode(),
        json.dumps({**forecast_doc(), "hourly": "x"}).encode(),
        json.dumps(forecast_doc(current={"time": "t", "temperature_2m": None})).encode(),
        json.dumps(forecast_doc(current={"temperature_2m": 1})).encode(),
    ],
)
def test_parse_forecast_rejects_bad_input(body: bytes) -> None:
    with pytest.raises(WeatherError):
        parse_forecast(body)


def test_parse_forecast_rejects_no_days() -> None:
    doc = forecast_doc()
    doc["daily"]["time"] = []
    with pytest.raises(WeatherError, match="no current temperature"):
        parse_forecast(json.dumps(doc).encode())


def test_parse_alerts_sorts_by_severity_cleans_text_and_defaults() -> None:
    body = alerts_doc(
        alert("a", "Minor"),
        alert("b", "Extreme", instruction="Take <i>shelter</i>", ends="2026-11-14T00:00:00-06:00"),
        alert("c", "Bogus", expires="2026-11-13T20:00:00-06:00"),
        alert("d", None),
        alert("e", "Severe"),
    )
    got = parse_alerts(body)
    assert [a["id"] for a in got] == ["b", "e", "a", "c", "d"]
    assert got[0]["headline"] == "Headline" and got[0]["instruction"] == "Take shelter"
    assert got[0]["ends"] == "2026-11-14T00:00:00-06:00"
    assert [a["severity"] for a in got[3:]] == ["Unknown", "Unknown"]
    assert got[3]["ends"] == "2026-11-13T20:00:00-06:00" and got[4]["ends"] == ""


def test_parse_alerts_is_capped() -> None:
    got = parse_alerts(alerts_doc(*[alert(str(i), "Minor") for i in range(25)]))
    assert len(got) == weather.MAX_ALERTS


def test_parse_alerts_empty_is_fine() -> None:
    assert parse_alerts(alerts_doc()) == []


@pytest.mark.parametrize("body", [b"nope", b"{}", b'{"features": 5}'])
def test_parse_alerts_rejects_bad_input(body: bytes) -> None:
    with pytest.raises(WeatherError):
        parse_alerts(body)


def make_getter(forecast: bytes | Exception, alerts: bytes | Exception) -> Any:
    def get(url: str) -> bytes:
        result = forecast if "open-meteo" in url else alerts
        if isinstance(result, Exception):
            raise result
        return result

    return get


def test_build_weather_combines_forecast_and_alerts() -> None:
    getter = make_getter(json.dumps(forecast_doc()).encode(), alerts_doc(alert("a", "Severe")))
    w = build_weather(LAT, LON, getter=getter, now=NOW)
    assert w["generated"] == "2026-11-13T12:00:00+00:00"
    assert w["alerts_ok"] is True and [a["id"] for a in w["alerts"]] == ["a"]
    assert {"current", "hourly", "daily"} <= w.keys()


def test_build_weather_asks_nws_for_the_point() -> None:
    urls: list[str] = []

    def get(url: str) -> bytes:
        urls.append(url)
        return json.dumps(forecast_doc()).encode() if "open-meteo" in url else alerts_doc()

    build_weather(LAT, LON, getter=get)
    assert "https://api.weather.gov/alerts/active?point=40.0000,-90.0000" in urls


@pytest.mark.parametrize("bad", [FeedError("fetch failed: 500"), b"garbage"])
def test_alerts_failing_only_flips_alerts_ok(bad: bytes | Exception) -> None:
    w = build_weather(LAT, LON, getter=make_getter(json.dumps(forecast_doc()).encode(), bad), now=NOW)
    assert w["alerts"] == [] and w["alerts_ok"] is False and w["current"]["temp"] == 41.0


@pytest.mark.parametrize("bad", [FeedError("fetch failed: 500"), b"garbage"])
def test_forecast_failing_raises(bad: bytes | Exception) -> None:
    with pytest.raises(WeatherError):
        build_weather(LAT, LON, getter=make_getter(bad, alerts_doc()))


def test_default_getter_uses_json_accept_and_short_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_fetch(url: str, **kw: Any) -> bytes:
        calls.append((url, kw))
        return json.dumps(forecast_doc()).encode() if "open-meteo" in url else alerts_doc()

    monkeypatch.setattr(weather, "fetch", fake_fetch)
    build_weather(LAT, LON)
    assert len(calls) == 2
    expected = {
        "accept": weather.JSON_ACCEPT,
        "deadline_seconds": weather.DEADLINE_SECONDS,
        "user_agent": weather.WEATHER_USER_AGENT,
    }
    assert all(kw == expected for _, kw in calls)


def test_parse_alerts_skips_a_malformed_alert_and_keeps_the_rest() -> None:
    body = json.dumps(
        {"features": [{}, {"properties": {}}, {"properties": None}, json.loads(alerts_doc(alert("ok", "Severe")))["features"][0]]}
    )
    assert [a["id"] for a in parse_alerts(body.encode())] == ["ok"]


@pytest.mark.parametrize(("raw", "expected"), [(1, True), (0, False), (None, None), ("x", None)])
def test_is_day_degrades_to_unknown(raw: Any, expected: bool | None) -> None:
    doc = forecast_doc()
    doc["current"]["is_day"] = raw
    assert parse_forecast(json.dumps(doc).encode())["current"]["is_day"] is expected


def test_a_stalled_request_times_out_instead_of_hanging(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    release = threading.Event()
    monkeypatch.setattr(weather, "WAIT_SECONDS", 0.05)

    def slow(url: str) -> bytes:
        if "open-meteo" in url:
            return json.dumps(forecast_doc()).encode()
        release.wait(5)
        return alerts_doc()

    got = build_weather(LAT, LON, getter=slow)
    assert got["alerts_ok"] is False and got["alerts"] == []
    release.set()

    def slow_forecast(url: str) -> bytes:
        release.clear()
        release.wait(5)
        return b""

    with pytest.raises(WeatherError, match="timed out"):
        build_weather(LAT, LON, getter=slow_forecast)
    release.set()
