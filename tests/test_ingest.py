import json
from typing import Any

import pytest

from ingest.config import LOCATION_TTL_SECONDS, ConfigError, cached_location, load_location, parse_location, reset_location_cache

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


def test_cached_location_is_reread_only_after_the_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    reads: list[dict] = []

    def load() -> dict:
        reads.append({**LOCATION, "town": f"read{len(reads) + 1}"})
        return reads[-1]

    monkeypatch.setattr("ingest.config.load_location", load)
    monkeypatch.setattr("ingest.config.time.monotonic", lambda: clock[0])
    reset_location_cache()
    assert cached_location()["town"] == "read1" and cached_location()["town"] == "read1"
    assert len(reads) == 1
    clock[0] += LOCATION_TTL_SECONDS - 1
    assert cached_location()["town"] == "read1"
    clock[0] += 2  # past the TTL: an edit made meanwhile is picked up
    assert cached_location()["town"] == "read2"
    reset_location_cache()


def test_a_failed_refresh_keeps_the_last_good_location_but_a_failed_first_read_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    ok = [True]

    def load() -> dict:
        if not ok[0]:
            raise ConfigError("ssm is down")
        return LOCATION

    monkeypatch.setattr("ingest.config.load_location", load)
    monkeypatch.setattr("ingest.config.time.monotonic", lambda: clock[0])
    reset_location_cache()
    ok[0] = False
    with pytest.raises(ConfigError):
        cached_location()  # nothing cached yet: the failure is raised, and not remembered
    ok[0] = True
    assert cached_location() == LOCATION
    ok[0] = False
    clock[0] += LOCATION_TTL_SECONDS + 1
    assert cached_location() == LOCATION  # the refresh failed: the last good value is used
    reset_location_cache()


def test_parse_location_accepts_an_optional_watch_key() -> None:
    assert parse_location(json.dumps({**LOCATION, "watch_key": "a1" * 10}))["watch_key"] == "a1" * 10
    assert "watch_key" not in parse_location(json.dumps(LOCATION))


@pytest.mark.parametrize("key", ["short", "UPPERCASE" * 3, "has-dash-in-it-xxxx", "x" * 65, 5, ""])
def test_parse_location_rejects_a_bad_watch_key(key: object) -> None:
    with pytest.raises(ConfigError, match="watch_key"):
        parse_location(json.dumps({**LOCATION, "watch_key": key}))


def test_the_quotes_file_is_named_by_a_hash_not_by_the_key() -> None:
    from ingest.config import watch_name

    name = watch_name("abc")
    assert name == "watch-ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
