"""The optional local feeds parameter (the village's own and alert feeds): parsing, the never-an-error loader, cache, merge."""

import json
from typing import Any

import pytest
from botocore.exceptions import ClientError

from ingest.config import (
    LOCATION_TTL_SECONDS,
    ConfigError,
    cached_local_feeds,
    load_local_feeds,
    merged_local_feeds,
    parse_local_feeds,
    parse_location,
    reset_local_feeds_cache,
)

LOCATION = {"town": "Exampleville", "lat": 40.0, "lon": -90.0, "nearby": ["Springfield"], "feeds": ["https://example.com/rss"]}
FEEDS = {"official": ["https://village.example/news.xml"], "alerts": ["https://village.example/alerts.xml"]}
NONE = {"official": [], "alerts": []}


class Ssm:
    def __init__(self, value: str | None = None, code: str | None = None) -> None:
        self.value, self.code = value, code
        self.asked: list[str] = []

    def get_parameter(self, Name: str) -> dict[str, Any]:  # noqa: N803  (boto3's signature)
        self.asked.append(Name)
        if self.code:
            raise ClientError({"Error": {"Code": self.code}}, "GetParameter")
        return {"Parameter": {"Value": self.value}}


@pytest.fixture(autouse=True)
def clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_FEEDS_PARAM", "/news/local-feeds")
    reset_local_feeds_cache()


def test_parse_takes_both_lists_each_optional() -> None:
    assert parse_local_feeds(json.dumps(FEEDS)) == FEEDS
    assert parse_local_feeds("{}") == NONE
    assert parse_local_feeds(json.dumps({"alerts": ["https://v.example/a"]})) == {
        "official": [],
        "alerts": ["https://v.example/a"],
    }


@pytest.mark.parametrize(
    "raw", ["nope", "[]", '{"official": "x"}', '{"alerts": [1]}', '{"official": [""]}', '{"alerts": {"a": 1}}']
)
def test_parse_rejects_bad_input(raw: str) -> None:
    with pytest.raises(ConfigError):
        parse_local_feeds(raw)


def test_load_reads_the_named_parameter() -> None:
    ssm = Ssm(json.dumps(FEEDS))
    assert load_local_feeds(ssm) == FEEDS and ssm.asked == ["/news/local-feeds"]


def test_load_is_empty_when_the_name_is_unset_or_the_parameter_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    assert load_local_feeds(Ssm(code="ParameterNotFound")) == NONE
    monkeypatch.delenv("LOCAL_FEEDS_PARAM")
    assert load_local_feeds(Ssm("{}")) == NONE


def test_load_is_none_when_unreadable_and_never_logs_the_value(caplog: pytest.LogCaptureFixture) -> None:
    assert load_local_feeds(Ssm(code="AccessDeniedException")) is None
    assert load_local_feeds(Ssm("{not json: https://secret.example/feed")) is None
    assert load_local_feeds(Ssm('{"official": "https://secret.example/feed"}')) is None
    assert "secret.example" not in caplog.text


def test_cache_never_raises_keeps_the_last_good_lists_and_rereads_after_the_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    answers: list[dict[str, list[str]] | None] = [None]  # the first read fails
    asked: list[int] = []

    def load() -> dict[str, list[str]] | None:
        asked.append(1)
        return answers[0]

    monkeypatch.setattr("ingest.config.load_local_feeds", load)
    monkeypatch.setattr("ingest.config.time.monotonic", lambda: clock[0])
    assert cached_local_feeds() == NONE  # a failed first read: none, and not cached
    answers[0] = FEEDS
    assert cached_local_feeds() == FEEDS and cached_local_feeds() == FEEDS and len(asked) == 2  # then cached
    clock[0] += LOCATION_TTL_SECONDS + 1
    answers[0] = None  # a failed refresh keeps the last good lists
    assert cached_local_feeds() == FEEDS


def test_merge_reads_official_from_both_places_once_and_keeps_alerts_out_of_official() -> None:
    location = {**LOCATION, "official": ["https://a.example/f", "https://village.example/news.xml"]}
    extra = {
        "official": ["https://village.example/news.xml", "https://b.example/f", "https://village.example/alerts.xml"],
        "alerts": FEEDS["alerts"] * 2,
    }
    official, alerts = merged_local_feeds(location, extra)
    assert official == ["https://a.example/f", "https://village.example/news.xml", "https://b.example/f"]  # each once, in order
    assert alerts == ["https://village.example/alerts.xml"]  # once, and an alert feed is not also official
    assert merged_local_feeds(LOCATION, NONE) == ([], [])


def test_the_location_parameter_does_not_know_alerts() -> None:
    assert "alerts" not in parse_location(json.dumps(LOCATION))
