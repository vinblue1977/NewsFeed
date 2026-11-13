import json
from typing import Any

import pytest

from ingest.config import ConfigError, load_location, parse_location
from ingest.handler import handler

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
    ["not json", "[]", json.dumps({**LOCATION, "lat": "40"}), json.dumps({**LOCATION, "lat": True}), json.dumps({"town": "x"})],
)
def test_parse_location_rejects_bad_input(raw: str) -> None:
    with pytest.raises(ConfigError):
        parse_location(raw)


def test_handler_returns_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ingest.handler.load_location", lambda: LOCATION)
    result = handler({}, object())
    assert result["status"] == "ok"
    assert result["local_feeds"] == 1


def test_load_location_creates_a_client_when_none_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCATION_PARAM", "/news/location")
    monkeypatch.setattr("ingest.config.boto3.client", lambda name: FakeSsm(json.dumps(LOCATION)))
    assert load_location()["town"] == "Exampleville"
