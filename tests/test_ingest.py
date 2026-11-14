import json
from typing import Any

import pytest

from ingest.config import ConfigError, cached_location, load_location, parse_location

LOCATION = {"town": "Exampleville", "lat": 40.0, "lon": -90.0, "nearby": ["Springfield"], "feeds": ["https://example.com/rss"]}


class FakeSsm:
    def __init__(self, value: str) -> None:
        self.value = value
        self.asked: list[str] = []

    def get_parameter(self, Name: str) -> dict[str, Any]:  # noqa: N803  (boto3's signature)
        self.asked.append(Name)
        return {"Parameter": {"Value": self.value}}


def test_load_location_reads_the_named_parameter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCATION_PARAM", "/news/location")
    ssm = FakeSsm(json.dumps(LOCATION))
    assert load_location(ssm) == LOCATION
    assert ssm.asked == ["/news/location"]


def test_load_location_needs_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCATION_PARAM", raising=False)
    with pytest.raises(ConfigError, match="LOCATION_PARAM"):
        load_location(FakeSsm("{}"))


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        json.dumps({**LOCATION, "lat": "40"}),
        json.dumps({**LOCATION, "lat": True}),
        json.dumps({"town": "x"}),
        json.dumps({**LOCATION, "feeds": [None]}),
        json.dumps({**LOCATION, "nearby": [1]}),
        json.dumps({**LOCATION, "lat": 999}),
    ],
)
def test_parse_location_rejects_bad_input(raw: str) -> None:
    with pytest.raises(ConfigError):
        parse_location(raw)


def test_load_location_creates_a_client_when_none_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCATION_PARAM", "/news/location")
    monkeypatch.setattr("ingest.config.boto3.client", lambda name: FakeSsm(json.dumps(LOCATION)))
    assert load_location()["town"] == "Exampleville"


def test_cached_location_reads_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr("ingest.config.load_location", lambda: calls.append(1) or LOCATION)
    cached_location.cache_clear()
    assert cached_location() == cached_location() == LOCATION
    assert len(calls) == 1
    cached_location.cache_clear()


@pytest.mark.parametrize("tickers", [[], ["^GSPC", "AAA.NS", "BTC-USD", "EURUSD=X"]])
def test_parse_location_accepts_optional_tickers(tickers: list[str]) -> None:
    assert parse_location(json.dumps({**LOCATION, "tickers": tickers}))["tickers"] == tickers


@pytest.mark.parametrize(
    "tickers",
    ["AAA", [1], [""], ["has space"], ["x" * 16], ["AAA;rm"], [".."], ["."], ["-AAA"], [f"T{i}" for i in range(21)], None],
)
def test_parse_location_rejects_bad_tickers(tickers: object) -> None:
    with pytest.raises(ConfigError, match="tickers"):
        parse_location(json.dumps({**LOCATION, "tickers": tickers}))
