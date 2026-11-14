"""The watchlist endpoint and the saved symbol list."""

import base64
import io
import json
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError

from ingest import api
from ingest.watchlist import WatchlistError, normalize, read_watchlist

KEY = "k" * 20


class Store:
    """Stands in for both the S3 and Lambda clients."""

    def __init__(self, symbols: list[str] | None = None) -> None:
        self.symbols = symbols
        self.error = ""
        self.puts: list[dict[str, Any]] = []
        self.invokes: list[dict[str, Any]] = []

    def get_object(self, **kw: Any) -> Any:
        if self.error:
            raise ClientError({"Error": {"Code": self.error}}, "GetObject")
        if self.symbols is None:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(json.dumps({"symbols": self.symbols}).encode())}

    def put_object(self, **kw: Any) -> None:
        self.puts.append(kw)

    def invoke(self, **kw: Any) -> None:
        self.invokes.append(kw)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Store:
    s = Store(["OLD"])
    monkeypatch.setattr(boto3, "client", lambda name: s)
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    monkeypatch.setenv("WATCHLIST_KEY", "private/watchlist.json")
    monkeypatch.setenv("INGEST_FUNCTION", "ingest-fn")
    monkeypatch.setattr(api, "cached_location", lambda: {"watch_key": KEY})
    return s


def call(body: Any, method: str = "POST", **extra: Any) -> tuple[int, dict[str, Any]]:
    event = {"requestContext": {"http": {"method": method}}, "body": body if isinstance(body, str) else json.dumps(body), **extra}
    reply = api.handler(event, object())
    assert reply["headers"]["Cache-Control"] == "no-store"
    return reply["statusCode"], json.loads(reply["body"])


def test_reading_needs_the_key_and_returns_the_saved_symbols(store: Store) -> None:
    assert call({"key": KEY}) == (200, {"symbols": ["OLD"]})
    assert store.puts == [] and store.invokes == []


@pytest.mark.parametrize("key", ["wrong" * 4, "", None, 5, "k" * 19])
def test_a_wrong_key_is_refused_and_changes_nothing(store: Store, key: object) -> None:
    assert call({"key": key, "symbols": ["AAA"]})[0] == 403
    assert store.puts == [] and store.invokes == []


def test_no_configured_key_refuses_everything(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "cached_location", lambda: {})
    assert call({"key": ""})[0] == 403


def test_saving_normalizes_stores_privately_and_starts_a_refresh(store: Store) -> None:
    assert call({"key": KEY, "symbols": ["aaa", "AAA", " msft "]}) == (200, {"symbols": ["AAA", "MSFT"]})
    assert [(p["Key"], json.loads(p["Body"])) for p in store.puts] == [("private/watchlist.json", {"symbols": ["AAA", "MSFT"]})]
    assert json.loads(store.invokes[0]["Payload"]) == {"only": "markets", "force": True}
    assert store.invokes[0]["InvocationType"] == "Event"


def test_clearing_the_list_is_allowed(store: Store) -> None:
    assert call({"key": KEY, "symbols": []}) == (200, {"symbols": []})


def test_a_failed_refresh_does_not_undo_the_save(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "invoke", lambda **kw: 1 / 0)
    assert call({"key": KEY, "symbols": ["AAA"]})[0] == 200 and len(store.puts) == 1


@pytest.mark.parametrize("symbols", ["AAA", [1], ["has space"], ["x" * 16], [f"T{i}" for i in range(21)], {"a": 1}])
def test_bad_symbols_are_rejected(store: Store, symbols: object) -> None:
    assert call({"key": KEY, "symbols": symbols})[0] == 400 and store.puts == []


def test_other_methods_bad_json_and_big_bodies(store: Store) -> None:
    assert call({"key": KEY}, method="GET")[0] == 405
    assert call("not json")[0] == 400
    assert call("[1]")[0] == 400
    assert call({"symbols": []})[0] == 400  # no key at all
    assert call(json.dumps({"key": KEY, "pad": "x" * 3000}))[0] == 413


def test_a_base64_body_is_decoded(store: Store) -> None:
    encoded = base64.b64encode(json.dumps({"key": KEY}).encode()).decode()
    assert call(encoded, isBase64Encoded=True) == (200, {"symbols": ["OLD"]})


def test_normalize_and_read_watchlist(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    assert normalize(["^gspc", "aaa.ns"]) == ["^GSPC", "AAA.NS"]
    with pytest.raises(WatchlistError):
        normalize("AAA")
    assert read_watchlist(store) == ["OLD"]
    assert read_watchlist(Store(None)) == []  # no list yet
    assert read_watchlist(Store(["bad symbol"])) == []  # a corrupt list is no list


def test_a_storage_error_is_not_shown_as_an_empty_list(store: Store) -> None:
    store.error = "AccessDenied"
    assert call({"key": KEY})[0] == 502
    with pytest.raises(ClientError):
        read_watchlist(store)
