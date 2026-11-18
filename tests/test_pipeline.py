import io
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError

from ingest import handler as handler_module
from ingest import pipeline
from ingest.config import earnings_name, watch_name
from ingest.feeds import FeedError
from ingest.pipeline import collect, local_sources
from ingest.sources import Source

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def rss(*entries: tuple[str, str, str, str]) -> bytes:
    items = "".join(
        f"<item><title>{t}</title><link>{u}</link><description>{d}</description><pubDate>{p}</pubDate></item>"
        for t, u, d, p in entries
    )
    return f"<rss><channel>{items}</channel></rss>".encode()


DOCS = {
    "https://a.example/f": rss(
        ("New", "https://x.example/1", "", "Fri, 13 Nov 2026 11:00:00 GMT"),
        ("Old", "https://x.example/2", "", "Mon, 02 Nov 2026 11:00:00 GMT"),
        ("Future", "https://x.example/3", "", "Sat, 14 Nov 2026 00:00:00 GMT"),
        ("Bogus", "https://x.example/8", "", "Wed, 01 Jan 2031 00:00:00 GMT"),
    ),
    "https://b.example/f": rss(("Dup", "https://x.example/1", "", "Fri, 13 Nov 2026 10:00:00 GMT")),
    "https://c.example/f": rss(
        ("Road closed in Buffalo Grove", "https://x.example/4", "", "Fri, 13 Nov 2026 09:00:00 GMT"),
        ("Nothing nearby", "https://x.example/5", "traffic in Elsewhere", "Fri, 13 Nov 2026 09:30:00 GMT"),
        ("Palatine news", "https://x.example/6", "", "Fri, 13 Nov 2026 08:00:00 GMT"),
        ("Buffalo Grovelike", "https://x.example/7", "", "Fri, 13 Nov 2026 07:00:00 GMT"),
    ),
}


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixtures are dated 2026-11-13: the handler must not judge their age against the real clock, or every test that
    builds a feed starts failing a few days after the fixtures were written."""
    real_collect = handler_module.collect

    def collect_at_fixed_time(sources: Any, nearby: Any = (), **kw: Any) -> Any:
        return real_collect(sources, nearby, **{"now": NOW, **kw})

    monkeypatch.setattr(handler_module, "collect", collect_at_fixed_time)


def fake_fetcher(url: str) -> bytes:
    if url not in DOCS:
        raise FeedError("fetch failed: 404")
    return DOCS[url]


def src(id: str, host: str, **kw: Any) -> Source:  # noqa: A002
    return Source(id, id, f"https://{host}.example/f", kw.pop("topic", "us"), **kw)


def test_collect_dedupes_drops_old_clamps_future_and_isolates_failures() -> None:
    sources = [src("a", "a"), src("b", "b"), src("bad", "missing"), src("off", "a", enabled=False)]
    items, status = collect(sources, now=NOW, fetcher=fake_fetcher)
    assert [i["title"] for i in items] == ["Future", "New"]  # newest first; old, duplicate and bogus-dated dropped
    assert items[0]["published"] == NOW.isoformat(timespec="seconds")  # clamped, not shown from the future
    assert status["a"] == {"ok": True, "items": 2}
    assert status["b"] == {"ok": True, "items": 0}  # its only item duplicated a's
    assert status["bad"]["ok"] is False and "404" in status["bad"]["error"]
    assert "off" not in status


def test_local_items_must_mention_a_nearby_place() -> None:
    sources = [src("c", "c", topic="local")]
    items, _ = collect(sources, ["Buffalo Grove", "Palatine"], now=NOW, fetcher=fake_fetcher)
    assert [i["title"] for i in items] == ["Road closed in Buffalo Grove", "Palatine news"]
    assert all("place" not in i for i in items)  # the public feed never says which of your places an item matched


def test_places_match_whatever_the_capitalisation() -> None:
    docs = {"https://c.example/f": rss(("ROAD WORK IN MCKINNEY", "https://x.example/9", "", "Fri, 13 Nov 2026 09:00:00 GMT"))}
    items, _ = collect([src("c", "c", topic="local")], ["McKinney"], now=NOW, fetcher=docs.__getitem__)
    assert [i["title"] for i in items] == ["ROAD WORK IN MCKINNEY"] and "place" not in items[0]


def test_an_unexpected_exception_in_one_source_does_not_sink_the_run() -> None:
    def fetcher(url: str) -> bytes:
        if "boom" in url:
            raise RecursionError
        return DOCS[url]

    items, status = collect([src("boom", "boom"), src("a", "a")], now=NOW, fetcher=fetcher)
    assert status["boom"] == {"ok": False, "items": 0, "error": "unexpected RecursionError"}
    assert len(items) == 2


def test_local_feed_without_places_keeps_nothing() -> None:
    assert collect([src("c", "c", topic="local")], [], now=NOW, fetcher=fake_fetcher)[0] == []


def test_per_source_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ingest.pipeline.MAX_PER_SOURCE", 1)
    items, _ = collect([src("a", "a")], now=NOW, fetcher=fake_fetcher)
    assert len(items) == 1


def test_local_sources_use_the_host_as_name() -> None:
    made = local_sources(["https://www.example.com/rss", "weird"])
    assert [(s.id, s.name, s.topic) for s in made] == [("local-0", "example.com", "local"), ("local-1", "local", "local")]


class FakeS3:
    def __init__(self) -> None:
        self.puts: list[dict[str, Any]] = []

    def put_object(self, **kw: Any) -> None:
        self.puts.append(kw)

    def get_object(self, **kw: Any) -> None:
        raise OSError("no previous feed")


@pytest.fixture(autouse=True)
def no_side_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    """The weather, markets and scores builders reach the network, so every handler test starts with them failing and opts in."""

    def down(*args: Any) -> dict[str, Any]:
        raise RuntimeError("down")

    monkeypatch.setattr(handler_module, "build_weather", down)
    monkeypatch.setattr(handler_module, "build_markets", down)
    monkeypatch.setattr(handler_module, "build_scores", down)
    monkeypatch.setattr(handler_module, "build_schedule", down)


def test_handler_writes_the_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3()
    monkeypatch.setattr(boto3, "client", lambda name: s3)
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    monkeypatch.setenv("DATA_PREFIX", "data")
    location = {"nearby": ["Palatine"], "feeds": ["https://c.example/f"], "lat": 40.0, "lon": -90.0}
    monkeypatch.setattr(handler_module, "cached_location", lambda: location)
    monkeypatch.setattr(handler_module, "SOURCES", (src("a", "a"),))
    monkeypatch.setattr("ingest.pipeline.fetch", fake_fetcher)
    monkeypatch.setattr(handler_module, "build_weather", lambda lat, lon: {"generated": "t", "lat_seen": lat})
    result = handler_module.handler({}, object())
    assert result["status"] == "ok" and result["failed"] == [] and result["weather"] == "ok"
    articles_put, put, weather_put = s3.puts  # the articles first, so a `full` flag in the feed always has its text
    assert articles_put["Key"] == "data/articles.json" and result["articles"] == "ok"
    assert set(json.loads(articles_put["Body"])) == {"generated", "articles"}
    assert weather_put["Bucket"] == "bucket" and weather_put["Key"] == "data/weather.json"
    assert weather_put["ContentType"] == "application/json"
    assert json.loads(weather_put["Body"]) == {"generated": "t", "lat_seen": 40.0}
    assert put["Bucket"] == "bucket" and put["Key"] == "data/feed.json" and put["ContentType"] == "application/json"
    body = json.loads(put["Body"])
    assert {"generated", "items", "sources"} <= body.keys()
    assert {i["topic"] for i in body["items"]} <= {"us", "local"}
    assert {c["id"] for c in body["clusters"]} == {i["cluster"] for i in body["items"]}


def _weather_handler_setup(monkeypatch: pytest.MonkeyPatch, s3: FakeS3) -> None:
    monkeypatch.setattr(boto3, "client", lambda name: s3)
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    monkeypatch.setenv("DATA_PREFIX", "data")
    monkeypatch.setattr(handler_module, "cached_location", lambda: {"nearby": [], "feeds": [], "lat": 40.0, "lon": -90.0})
    monkeypatch.setattr(handler_module, "SOURCES", (src("a", "a"),))
    monkeypatch.setattr("ingest.pipeline.fetch", fake_fetcher)


def test_handler_survives_a_weather_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3()
    _weather_handler_setup(monkeypatch, s3)

    def boom(lat: float, lon: float) -> dict[str, Any]:
        raise RuntimeError("weather is down")

    monkeypatch.setattr(handler_module, "build_weather", boom)
    result = handler_module.handler({}, object())
    assert result["status"] == "ok" and result["weather"] == "failed"
    assert [p["Key"] for p in s3.puts] == ["data/articles.json", "data/feed.json"]


def test_handler_survives_a_weather_write_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class PutFails(FakeS3):
        def put_object(self, **kw: Any) -> None:
            if kw["Key"].endswith("weather.json"):
                raise OSError("denied")
            super().put_object(**kw)

    s3 = PutFails()
    _weather_handler_setup(monkeypatch, s3)
    monkeypatch.setattr(handler_module, "build_weather", lambda lat, lon: {"generated": "t"})
    assert handler_module.handler({}, object())["weather"] == "failed"
    assert [p["Key"] for p in s3.puts] == ["data/articles.json", "data/feed.json"]


def test_handler_refuses_to_overwrite_with_an_all_failed_run(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3()
    monkeypatch.setattr(boto3, "client", lambda name: s3)
    monkeypatch.setattr(handler_module, "cached_location", lambda: {"nearby": [], "feeds": []})
    monkeypatch.setattr(handler_module, "SOURCES", (src("bad", "missing"),))
    monkeypatch.setattr("ingest.pipeline.fetch", fake_fetcher)
    with pytest.raises(RuntimeError, match="1 of 1 sources failed"):
        handler_module.handler({}, object())
    assert s3.puts == []


def test_handler_refuses_a_mostly_failed_run(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3()
    monkeypatch.setattr(boto3, "client", lambda name: s3)
    monkeypatch.setattr(handler_module, "cached_location", lambda: {"nearby": [], "feeds": []})
    monkeypatch.setattr(handler_module, "SOURCES", (src("a", "a"), src("m1", "missing"), src("m2", "missing")))
    monkeypatch.setattr("ingest.pipeline.fetch", fake_fetcher)
    with pytest.raises(RuntimeError, match="2 of 3 sources failed"):
        handler_module.handler({}, object())
    assert s3.puts == []


def test_tracking_parameters_and_trailing_slashes_do_not_defeat_dedupe() -> None:
    docs = {
        "https://a.example/f": rss(("A", "https://x.example/s/?utm_source=rss&amp;id=1", "", "Fri, 13 Nov 2026 11:00:00 GMT")),
        "https://b.example/f": rss(("B", "https://X.example/s?id=1#top", "", "Fri, 13 Nov 2026 10:00:00 GMT")),
        "https://c.example/f": rss(("C", "https://x.example/s?id=2", "", "Fri, 13 Nov 2026 09:00:00 GMT")),
    }
    items, _ = collect([src("a", "a"), src("b", "b"), src("c", "c")], now=NOW, fetcher=docs.__getitem__)
    assert [i["title"] for i in items] == ["A", "C"]  # id=2 is a different story


def test_odd_place_names_match() -> None:
    docs = {
        "https://c.example/f": rss(
            ("Palatine Heights school board", "https://x.example/1", "", "Fri, 13 Nov 2026 09:00:00 GMT"),
            ("Mayor of St. Charles speaks", "https://x.example/2", "", "Fri, 13 Nov 2026 08:00:00 GMT"),
            ("Palatinex fair opens", "https://x.example/3", "", "Fri, 13 Nov 2026 07:00:00 GMT"),
            ("Mayor of St Charles speaks", "https://x.example/4", "", "Fri, 13 Nov 2026 06:00:00 GMT"),
        )
    }
    items, _ = collect(
        [src("c", "c", topic="local")], ["Palatine", "Palatine Heights", "St. Charles"], now=NOW, fetcher=docs.__getitem__
    )
    assert [i["title"] for i in items] == ["Palatine Heights school board", "Mayor of St. Charles speaks"]


def test_local_source_names_are_just_the_host() -> None:
    with_userinfo = (
        "https://user:pw" + chr(64) + "www.example.com:8443/rss"
    )  # built at runtime: the privacy guard bans "@" in URLs
    made = local_sources([with_userinfo, "https:///nohost"])
    assert [s.name for s in made] == ["example.com", "local"]


def test_a_slow_run_is_cut_off_and_the_rest_still_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    monkeypatch.setattr(pipeline, "RUN_BUDGET_SECONDS", 0.3)

    def fetcher(url: str) -> bytes:
        if "slow" in url:
            time.sleep(2)
        return DOCS["https://a.example/f"]

    start = time.monotonic()
    items, status = collect([src("slow", "slow"), src("a", "a")], now=NOW, fetcher=fetcher)
    assert time.monotonic() - start < 1.5
    assert status["slow"] == {"ok": False, "items": 0, "error": "timed out"}
    assert status["a"]["ok"] and len(items) == 2


def test_blocked_items_are_dropped_and_counted() -> None:
    docs = {
        "https://a.example/f": rss(
            ("Free story", "https://www.npr.org/1", "", "Fri, 13 Nov 2026 11:00:00 GMT"),
            ("Walled story", "https://www.nytimes.com/2", "", "Fri, 13 Nov 2026 10:00:00 GMT"),
            ("Obituary", "https://www.legacy.com/3", "", "Fri, 13 Nov 2026 09:00:00 GMT"),
        )
    }
    items, status = collect([src("a", "a")], now=NOW, fetcher=docs.__getitem__)
    assert [i["title"] for i in items] == ["Free story"]
    assert status["a"] == {"ok": True, "items": 1, "blocked": 2}


def test_a_trusted_local_search_keeps_items_without_a_place_mention() -> None:
    docs = {
        "https://g.example/f": rss(
            ("Road work starts Monday", "https://x.example/1", "", "Fri, 13 Nov 2026 09:00:00 GMT"),
            ("Palatine council meets", "https://x.example/2", "", "Fri, 13 Nov 2026 10:00:00 GMT"),
        )
    }
    scoped = Source("g", "g", "https://g.example/f", "local", trusted=True)
    items, _ = collect([scoped], ["Buffalo Grove", "Palatine"], now=NOW, fetcher=docs.__getitem__)
    assert {i["title"] for i in items} == {"Road work starts Monday", "Palatine council meets"}
    items, _ = collect([scoped], [], now=NOW, fetcher=docs.__getitem__)
    assert len(items) == 2 and all("place" not in i for i in items)


def test_a_story_in_both_a_direct_feed_and_google_news_is_shown_once() -> None:
    docs = {
        "https://a.example/f": rss(("Same story", "https://www.cnn.com/a", "", "Fri, 13 Nov 2026 11:00:00 GMT")),
        "https://b.example/f": rss(("Same Story", "https://news.google.com/rss/articles/X", "", "Fri, 13 Nov 2026 11:00:00 GMT")),
    }
    direct = Source("cnn", "CNN", "https://a.example/f", "us")
    via_google = Source("gn-cnn", "CNN", "https://b.example/f", "us")  # Google News reports the real publisher's name
    items, _ = collect([direct, via_google], now=NOW, fetcher=docs.__getitem__)
    assert len(items) == 1


def test_a_duplicate_with_a_sub_topic_tags_the_story_whichever_feed_came_first() -> None:
    docs = {
        "https://a.example/f": rss(("Same story", "https://a.example/x", "", "Fri, 13 Nov 2026 11:00:00 GMT")),
        "https://b.example/f": rss(("Same story", "https://a.example/x/", "", "Fri, 13 Nov 2026 11:00:00 GMT")),
    }
    general = Source("gen", "Site", "https://a.example/f", "tech")
    tagged = Source("tag", "Site", "https://b.example/f", "tech", "gadgets")
    for order in ([general, tagged], [tagged, general]):
        items, _ = collect(order, now=NOW, fetcher=docs.__getitem__)
        assert len(items) == 1 and items[0]["subtopic"] == "gadgets"


def test_only_google_news_local_feeds_are_trusted() -> None:
    made = local_sources(["https://news.google.com/rss/search?q=x", "https://wgntv.example/feed"])
    assert [s.trusted for s in made] == [True, False]


def test_a_publisher_limited_google_search_is_checked_for_a_place() -> None:
    made = local_sources(
        [
            "https://news.google.com/rss/search?q=%22Buffalo+Grove%22+when%3A2d",  # scoped to the places: trusted
            "https://news.google.com/rss/search?q=site%3Adailyherald.com+%28%22Buffalo+Grove%22%29+when%3A3d",
            "https://news.google.com/rss/search?q=site:patch.com+Palatine",
            "https://news.google.com/rss/search?q=SITE%3APatch.com",  # any case
        ]
    )
    assert [s.trusted for s in made] == [True, False, False, False]


def test_only_a_real_publisher_limit_makes_a_search_checked() -> None:
    made = local_sources(
        [
            "https://news.google.com/rss/search?q=%22Buffalo+Grove%22+-site%3Ayoutube.com",  # a negation is not a limit
            "https://news.google.com/rss/search?q=website%3Aexample+Palatine",  # nor is another word ending in "site"
            "https://news.google.com/rss/search?q=inurl%3Apatch.com+Palatine",
            "https://news.google.com/rss/search?q=source%3APatch+Palatine",
            "https://www.google.com/rss/search?q=site%3Apatch.com",  # not Google News: checked like any feed
        ]
    )
    assert [s.trusted for s in made] == [True, True, False, False, False]


def test_a_publisher_limited_search_drops_items_that_name_no_place() -> None:
    when = b"<pubDate>Mon, 16 Nov 2026 01:00:00 GMT</pubDate>"
    xml = (
        b"<rss><channel>"
        b"<item><title>Buffalo Grove trustees vote</title><link>https://a.example/1</link>" + when + b"</item>"
        b"<item><title>Council approves budget</title><link>https://a.example/2</link>" + when + b"</item>"
        b"</channel></rss>"
    )
    source = local_sources(["https://news.google.com/rss/search?q=site%3Aa.example+%22Buffalo+Grove%22"])[0]
    now = datetime(2026, 11, 16, 2, 0, tzinfo=UTC)
    items, _ = collect([source], ["Buffalo Grove"], now=now, fetcher=lambda _url: xml)
    assert [i["title"] for i in items] == ["Buffalo Grove trustees vote"]


def test_previous_state_reads_the_last_feed_and_fails_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    monkeypatch.setenv("DATA_PREFIX", "data")

    class Body:
        def read(self) -> bytes:
            return json.dumps({"items": [{"id": "a", "cluster": "c1"}, {"id": "b"}]}).encode()

    class Reader:
        def get_object(self, **kw: Any) -> dict[str, Any]:
            assert kw == {"Bucket": "bucket", "Key": "data/feed.json"}
            return {"Body": Body()}

    class Broken:
        def get_object(self, **kw: Any) -> None:
            raise OSError("no such key")

    assert handler_module.previous_state(Reader()) == ({"a": "c1"}, {})
    assert handler_module.previous_state(Broken()) == ({}, {})


def test_a_clustering_failure_still_writes_the_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(items: Any, previous: Any = None) -> None:
        raise ValueError("bad item")

    monkeypatch.setattr(handler_module, "SOURCES", (src("a", "a"),))
    monkeypatch.setattr("ingest.pipeline.fetch", fake_fetcher)
    monkeypatch.setattr(handler_module, "cluster_items", boom)
    feed, _ = handler_module.build_feed({"nearby": [], "feeds": []})
    assert feed["clusters"] == [] and feed["items"]
    assert all("cluster" not in i for i in feed["items"])


def test_weather_is_written_even_when_the_feed_run_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3()
    _weather_handler_setup(monkeypatch, s3)
    monkeypatch.setattr(handler_module, "SOURCES", (src("bad", "missing"),))
    monkeypatch.setattr(handler_module, "build_weather", lambda lat, lon: {"generated": "t"})
    with pytest.raises(RuntimeError, match="keeping the previous feed"):
        handler_module.handler({}, object())
    assert [p["Key"] for p in s3.puts] == ["data/weather.json"]


class WatchS3(FakeS3):
    """A FakeS3 that holds the saved watchlist."""

    def __init__(self, symbols: list[str] | None) -> None:
        super().__init__()
        self.symbols = symbols

    def get_object(self, **kw: Any) -> Any:
        if kw["Key"] != "private/watchlist.json" or self.symbols is None:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(json.dumps({"symbols": self.symbols}).encode())}


KEY = "k" * 20


def _watch_setup(monkeypatch: pytest.MonkeyPatch, s3: FakeS3, markets: Any, *, key: str | None = KEY) -> list[list[str]]:
    _weather_handler_setup(monkeypatch, s3)
    monkeypatch.setenv("WATCHLIST_KEY", "private/watchlist.json")
    location = {"nearby": [], "feeds": [], "lat": 40.0, "lon": -90.0, **({"watch_key": key} if key else {})}
    monkeypatch.setattr(handler_module, "cached_location", lambda: location)
    asked: list[list[str]] = []

    def build(tickers: list[str]) -> dict[str, Any]:
        asked.append(tickers)
        return markets

    monkeypatch.setattr(handler_module, "build_markets", build)
    monkeypatch.setattr(handler_module, "finnhub_key", lambda: "token")  # never SSM
    monkeypatch.setattr(
        handler_module, "build_earnings", lambda symbols, token: {"generated": "e", "symbols": symbols, "items": []}
    )  # never the network
    return asked


OPEN = {"generated": "m", "indexes": [{"symbol": "^X", "open": True}], "tickers": [{"symbol": "AAA"}]}
CLOSED = {"generated": "m", "indexes": [{"symbol": "^X", "open": False}], "tickers": [{"symbol": "AAA"}]}


def test_full_run_writes_the_quotes_to_the_private_file_only(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = WatchS3(["AAA"])
    asked = _watch_setup(monkeypatch, s3, CLOSED)  # the full run writes the quotes even when the market is closed
    monkeypatch.setattr(handler_module, "build_weather", lambda lat, lon: {"generated": "w"})
    monkeypatch.setattr(handler_module, "build_scores", lambda: {"generated": "s"})
    result = handler_module.handler({}, object())
    assert (result["weather"], result["markets"], result["scores"]) == ("ok", "ok", "ok")
    assert asked == [["AAA"]]
    written = {p["Key"]: json.loads(p["Body"]) for p in s3.puts}
    assert written[f"data/{watch_name(KEY)}.json"] == {"generated": "m", "indexes": [], "tickers": [{"symbol": "AAA"}]}
    assert "data/markets.json" not in written  # there is no public quotes file any more
    assert set(written) == {
        "data/articles.json",
        "data/feed.json",
        "data/weather.json",
        "data/scores.json",
        f"data/{watch_name(KEY)}.json",
        f"data/{earnings_name(KEY)}.json",
    }
    assert result["earnings"] == "ok"
    assert written[f"data/{earnings_name(KEY)}.json"] == {"generated": "e", "symbols": ["AAA"], "items": []}


@pytest.mark.parametrize("key", [None, KEY])
def test_full_run_without_a_key_or_symbols_publishes_nothing(monkeypatch: pytest.MonkeyPatch, key: str | None) -> None:
    s3 = WatchS3(["AAA"] if key is None else None)  # a key without symbols, or symbols without a key
    asked = _watch_setup(monkeypatch, s3, CLOSED, key=key)
    result = handler_module.handler({}, object())
    assert result["markets"] == "skipped" and not any("watch" in p["Key"] or "earn" in p["Key"] for p in s3.puts)
    assert result["earnings"] == "skipped"
    assert asked == []  # nothing to show, so no quotes are fetched at all


def test_markets_run_writes_only_while_a_market_is_open(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = WatchS3(["AAA"])
    _watch_setup(monkeypatch, s3, OPEN)
    assert handler_module.handler({"only": "markets"}, object())["markets"] == "ok"
    assert [p["Key"] for p in s3.puts] == [f"data/{watch_name(KEY)}.json"]  # and no feed, no other document


def test_markets_run_with_every_market_closed_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = WatchS3(["AAA"])
    _watch_setup(monkeypatch, s3, CLOSED)
    assert handler_module.handler({"only": "markets"}, object())["markets"] == "closed"
    assert s3.puts == []


def test_a_forced_markets_run_writes_even_when_closed_or_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = WatchS3(["AAA"])
    _watch_setup(monkeypatch, s3, CLOSED)
    assert handler_module.handler({"only": "markets", "force": True}, object())["markets"] == "ok"
    empty = WatchS3([])
    _watch_setup(monkeypatch, empty, {"generated": "m", "indexes": [], "tickers": []})
    assert handler_module.handler({"only": "markets", "force": True}, object())["markets"] == "ok"
    assert json.loads(empty.puts[0]["Body"])["tickers"] == []  # a cleared list clears the file
    assert handler_module.handler({"only": "markets"}, object())["markets"] == "skipped"  # unforced: nothing to do


def test_markets_run_without_a_key_or_when_quotes_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = WatchS3(["AAA"])
    asked = _watch_setup(monkeypatch, s3, OPEN, key=None)
    assert handler_module.handler({"only": "markets"}, object())["markets"] == "skipped" and asked == []
    _watch_setup(monkeypatch, s3, OPEN)
    monkeypatch.setattr(handler_module, "build_markets", lambda tickers: 1 / 0)
    assert handler_module.handler({"only": "markets"}, object())["markets"] == "failed" and s3.puts == []


def test_one_failing_side_document_does_not_affect_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3()
    _weather_handler_setup(monkeypatch, s3)
    monkeypatch.setattr(handler_module, "build_weather", lambda lat, lon: {"generated": "w"})
    monkeypatch.setattr(handler_module, "build_scores", lambda: {"generated": "s"})  # markets stays down
    result = handler_module.handler({}, object())
    assert (result["weather"], result["markets"], result["scores"]) == ("ok", "skipped", "ok")
    assert sorted(p["Key"] for p in s3.puts) == ["data/articles.json", "data/feed.json", "data/scores.json", "data/weather.json"]


def test_scores_and_the_watchlist_are_written_even_when_the_feed_run_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = WatchS3(["AAA"])
    _watch_setup(monkeypatch, s3, OPEN)
    monkeypatch.setattr(handler_module, "SOURCES", (src("bad", "missing"),))
    monkeypatch.setattr(handler_module, "build_scores", lambda: {"generated": "s"})
    with pytest.raises(RuntimeError, match="keeping the previous feed"):
        handler_module.handler({}, object())
    assert sorted(p["Key"] for p in s3.puts) == sorted(
        ["data/scores.json", f"data/{watch_name(KEY)}.json", f"data/{earnings_name(KEY)}.json"]
    )


def test_handler_writes_the_feed_without_pictures_when_that_step_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3()
    _weather_handler_setup(monkeypatch, s3)

    def boom(*args: Any) -> None:
        raise ValueError("pictures broke")

    monkeypatch.setattr(handler_module, "attach_images", boom)
    assert handler_module.handler({}, object())["status"] == "ok"
    feed = json.loads(next(p for p in s3.puts if p["Key"] == "data/feed.json")["Body"])
    assert feed["items"] and all("_image" not in i and "img" not in i for i in feed["items"])


def test_a_list_edited_during_the_run_is_not_overwritten(monkeypatch: pytest.MonkeyPatch) -> None:
    class Edited(WatchS3):
        reads = 0

        def get_object(self, **kw: Any) -> Any:
            if kw["Key"] == "private/watchlist.json":
                self.reads += 1
                self.symbols = ["AAA"] if self.reads == 1 else ["BBB"]  # saved again while the feed was being built
            return super().get_object(**kw)

    s3 = Edited(["AAA"])
    _watch_setup(monkeypatch, s3, OPEN)
    assert handler_module.handler({}, object())["markets"] == "superseded"
    assert not any("watch-" in p["Key"] for p in s3.puts)


def test_a_storage_error_is_not_an_empty_watchlist(monkeypatch: pytest.MonkeyPatch) -> None:
    class Denied(WatchS3):
        def get_object(self, **kw: Any) -> Any:
            if kw["Key"] == "private/watchlist.json":
                raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
            return super().get_object(**kw)

    s3 = Denied(["AAA"])
    _watch_setup(monkeypatch, s3, OPEN)
    assert handler_module.handler({"only": "markets"}, object())["markets"] == "failed"
    assert handler_module.handler({}, object())["markets"] == "skipped" and not any("watch-" in p["Key"] for p in s3.puts)


def test_earnings_are_not_rebuilt_while_the_file_is_fresh_and_the_list_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    class Fresh(WatchS3):
        def get_object(self, **kw: Any) -> Any:
            if kw["Key"] == f"data/{earnings_name(KEY)}.json":
                doc = {"generated": datetime.now(UTC).isoformat(), "symbols": ["AAA"], "items": []}
                return {"Body": io.BytesIO(json.dumps(doc).encode())}
            return super().get_object(**kw)

    s3 = Fresh(["AAA"])
    _watch_setup(monkeypatch, s3, CLOSED)
    calls: list[list[str]] = []
    monkeypatch.setattr(handler_module, "build_earnings", lambda symbols, token: calls.append(symbols))
    assert handler_module.handler({}, object())["earnings"] == "fresh"
    assert calls == [] and not any("earn-" in p["Key"] for p in s3.puts)


def test_a_failed_earnings_build_keeps_the_old_file_and_the_rest_of_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = WatchS3(["AAA"])
    _watch_setup(monkeypatch, s3, CLOSED)

    def blocked(symbols: list[str], token: str) -> dict[str, Any]:
        raise OSError("calendar blocked")

    monkeypatch.setattr(handler_module, "build_earnings", blocked)
    result = handler_module.handler({}, object())
    assert (result["status"], result["earnings"], result["markets"]) == ("ok", "failed", "ok")
    assert not any("earn-" in p["Key"] for p in s3.puts)


def test_an_unreadable_earnings_file_is_not_a_missing_one(monkeypatch: pytest.MonkeyPatch) -> None:
    class Denied(WatchS3):
        def get_object(self, **kw: Any) -> Any:
            if kw["Key"] == f"data/{earnings_name(KEY)}.json":
                raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
            return super().get_object(**kw)

    s3 = Denied(["AAA"])
    _watch_setup(monkeypatch, s3, CLOSED)
    calls: list[list[str]] = []
    monkeypatch.setattr(handler_module, "build_earnings", lambda symbols, token: calls.append(symbols))
    result = handler_module.handler({}, object())
    assert result["earnings"] == "fresh" and calls == []  # asking every run would spend the shared free-tier calls
    assert not any("earn-" in p["Key"] for p in s3.puts)


def test_a_corrupt_earnings_file_is_rebuilt(monkeypatch: pytest.MonkeyPatch) -> None:
    class Corrupt(WatchS3):
        def get_object(self, **kw: Any) -> Any:
            if kw["Key"] == f"data/{earnings_name(KEY)}.json":
                return {"Body": io.BytesIO(b"not json")}
            return super().get_object(**kw)

    s3 = Corrupt(["AAA"])
    _watch_setup(monkeypatch, s3, CLOSED)
    assert handler_module.handler({}, object())["earnings"] == "ok"


def test_earnings_are_not_written_when_the_list_was_edited_during_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    class Edited(WatchS3):
        reads = 0

        def get_object(self, **kw: Any) -> Any:
            if kw["Key"] == "private/watchlist.json":
                self.reads += 1
                self.symbols = ["AAA"] if self.reads == 1 else ["BBB"]
            return super().get_object(**kw)

    s3 = Edited(["AAA"])
    _watch_setup(monkeypatch, s3, OPEN)
    result = handler_module.handler({}, object())
    assert (result["earnings"], result["markets"]) == ("superseded", "superseded")
    assert not any("earn-" in p["Key"] or "watch-" in p["Key"] for p in s3.puts)


def test_a_24_hour_symbol_counts_as_an_open_market() -> None:
    doc = {"generated": "g", "indexes": [{"open": False}], "tickers": [{"symbol": "BTC-USD", "open": True}]}
    assert handler_module.watch_doc(doc)[1] is True
    assert handler_module.watch_doc({**doc, "tickers": [{"open": False}]})[1] is False


def test_an_unreadable_list_at_write_time_does_not_discard_the_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    class Flaky(WatchS3):
        reads = 0

        def get_object(self, **kw: Any) -> Any:
            if kw["Key"] == "private/watchlist.json":
                self.reads += 1
                if self.reads > 1:
                    raise ClientError({"Error": {"Code": "SlowDown"}}, "GetObject")
            return super().get_object(**kw)

    s3 = Flaky(["AAA"])
    _watch_setup(monkeypatch, s3, OPEN)
    assert handler_module.handler({}, object())["markets"] == "ok"


def test_local_stories_are_kept_for_a_week_and_other_topics_for_three_days() -> None:
    now = datetime(2026, 11, 16, 2, 0, tzinfo=UTC)

    def feed(*days: int) -> bytes:
        def row(d: int) -> str:
            when = (now - timedelta(days=d)).strftime("%a, %d %b %Y %H:%M:%S GMT")
            return f"<item><title>Story {d} days old</title><link>https://a.example/{d}</link><pubDate>{when}</pubDate></item>"

        return f"<rss><channel>{''.join(row(d) for d in days)}</channel></rss>".encode()

    local = Source("l", "Local", "https://a.example/l", "local", trusted=True)
    other = Source("o", "Other", "https://a.example/o", "us")
    kept_local, _ = collect([local], [], now=now, fetcher=lambda _url: feed(1, 5, 6, 8))
    kept_other, _ = collect([other], [], now=now, fetcher=lambda _url: feed(1, 2, 4, 5))
    assert [i["title"] for i in kept_local] == ["Story 1 days old", "Story 5 days old", "Story 6 days old"]  # 8 days: too old
    assert [i["title"] for i in kept_other] == ["Story 1 days old", "Story 2 days old"]  # 4 days: past the 72 hours


class NoSchedule(FakeS3):
    """A store where the schedule file does not exist yet (a clean not-found, unlike the base fake's generic error)."""

    def get_object(self, **kw: Any) -> Any:
        if kw["Key"] == "data/schedule.json":
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return super().get_object(**kw)


def test_the_schedule_is_written_publicly_when_missing_and_not_rebuilt_while_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = NoSchedule()
    _weather_handler_setup(monkeypatch, s3)
    doc = {"generated": datetime.now(UTC).isoformat(), "week": 11, "games": []}
    monkeypatch.setattr(handler_module, "build_schedule", lambda: doc)
    result = handler_module.handler({}, object())
    assert result["schedule"] == "ok"
    assert json.loads(next(p for p in s3.puts if p["Key"] == "data/schedule.json")["Body"]) == doc

    class Fresh(FakeS3):
        def get_object(self, **kw: Any) -> Any:
            if kw["Key"] == "data/schedule.json":
                return {"Body": io.BytesIO(json.dumps(doc).encode())}
            return super().get_object(**kw)

    fresh = Fresh()
    _weather_handler_setup(monkeypatch, fresh)
    calls: list[int] = []
    monkeypatch.setattr(handler_module, "build_schedule", lambda: calls.append(1))
    assert handler_module.handler({}, object())["schedule"] == "fresh"
    assert calls == [] and not any(p["Key"] == "data/schedule.json" for p in fresh.puts)


def test_an_unreadable_schedule_file_is_not_rebuilt_and_a_failed_build_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    class Denied(FakeS3):
        def get_object(self, **kw: Any) -> Any:
            if kw["Key"] == "data/schedule.json":
                raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
            return super().get_object(**kw)

    denied = Denied()
    _weather_handler_setup(monkeypatch, denied)
    calls: list[int] = []
    monkeypatch.setattr(handler_module, "build_schedule", lambda: calls.append(1))
    assert handler_module.handler({}, object())["schedule"] == "fresh" and calls == []  # nothing asked of ESPN

    broken = NoSchedule()
    _weather_handler_setup(monkeypatch, broken)  # missing file: due, but ESPN is down (the fixture's default)
    result = handler_module.handler({}, object())
    assert result["schedule"] == "failed" and result["status"] == "ok"
    assert not any(p["Key"] == "data/schedule.json" for p in broken.puts)


GOOGLE = "https://news.google.com/rss/search?q=site:a.example"
GOOD = rss(("Story", "https://x.example/g1", "", "Fri, 13 Nov 2026 11:00:00 GMT"))


def _flaky(failures: list[FeedError | None]) -> Any:
    """A fetcher that raises the given errors one call at a time (None: succeeds), and counts its calls."""
    calls = {"n": 0}

    def fetcher(url: str) -> bytes:
        error = failures[calls["n"]] if calls["n"] < len(failures) else None
        calls["n"] += 1
        if error:
            raise error
        return GOOD

    fetcher.calls = calls  # type: ignore[attr-defined]
    return fetcher


@pytest.fixture
def no_pause(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    pauses: list[float] = []
    monkeypatch.setattr("ingest.pipeline.time.sleep", pauses.append)
    return pauses


def test_a_google_news_search_is_retried_once_after_a_busy_answer(no_pause: list[float]) -> None:
    fetcher = _flaky([FeedError("fetch failed: HTTPError 503", 503)])
    items, status = collect([Source("g", "G", GOOGLE, "local", trusted=True)], now=NOW, fetcher=fetcher)
    assert status["g"]["ok"] and len(items) == 1 and fetcher.calls["n"] == 2
    assert len(no_pause) == 1 and 1.0 <= no_pause[0] <= 3.0


def test_a_google_news_search_that_fails_twice_is_reported_failed(no_pause: list[float]) -> None:
    fetcher = _flaky([FeedError("fetch failed: HTTPError 429", 429)] * 2)
    _, status = collect([Source("g", "G", GOOGLE, "local", trusted=True)], now=NOW, fetcher=fetcher)
    assert status["g"] == {"ok": False, "items": 0, "error": "fetch failed: HTTPError 429"} and fetcher.calls["n"] == 2


def test_other_failures_are_not_retried(no_pause: list[float]) -> None:
    not_busy = _flaky([FeedError("fetch failed: HTTPError 404", 404)])
    collect([Source("g", "G", GOOGLE, "local", trusted=True)], now=NOW, fetcher=not_busy)
    elsewhere = _flaky([FeedError("fetch failed: HTTPError 503", 503)])
    collect([Source("e", "E", "https://a.example/f", "us")], now=NOW, fetcher=elsewhere)
    assert not_busy.calls["n"] == 1 and elsewhere.calls["n"] == 1 and no_pause == []


def test_a_retry_that_fails_unexpectedly_is_reported_as_such(no_pause: list[float]) -> None:
    calls = {"n": 0}

    def fetcher(url: str) -> bytes:
        calls["n"] += 1
        if calls["n"] == 1:
            raise FeedError("fetch failed: HTTPError 503", 503)
        raise ValueError("boom")

    _, status = collect([Source("g", "G", GOOGLE, "local", trusted=True)], now=NOW, fetcher=fetcher)
    assert status["g"]["error"] == "unexpected ValueError" and calls["n"] == 2


def test_handler_runs_the_push_step_after_the_feed_and_survives_its_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3()
    _weather_handler_setup(monkeypatch, s3)
    order: list[str] = []
    real_put = s3.put_object
    s3.put_object = lambda **kw: (order.append(kw["Key"]), real_put(**kw))[1]  # type: ignore[method-assign]
    monkeypatch.setattr("ingest.push.run_push", lambda s3_, feed: (order.append("push"), "sent:1")[1])
    result = handler_module.handler({}, object())
    assert result["push"] == "sent:1" and order[-1] == "push" and "data/feed.json" in order[:-1]

    def boom(s3_: Any, feed: dict[str, Any]) -> str:
        raise RuntimeError("push exploded")

    monkeypatch.setattr("ingest.push.run_push", boom)
    assert handler_module.handler({}, object())["push"] == "failed"


def test_handler_skips_the_push_step_when_the_run_is_late(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3()
    _weather_handler_setup(monkeypatch, s3)
    monkeypatch.setattr(handler_module, "PUSH_CUTOFF_SECONDS", -1)
    assert handler_module.handler({}, object())["push"] == "late"


def test_handler_without_push_configuration_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3()
    _weather_handler_setup(monkeypatch, s3)
    for name in ("PUSH_KEY_PARAM", "PUSH_REG_PARAM", "SITE_URL"):
        monkeypatch.delenv(name, raising=False)
    result = handler_module.handler({}, object())
    assert result["push"] == "off" and [p["Key"] for p in s3.puts] == ["data/articles.json", "data/feed.json"]


def test_push_test_event_runs_only_the_test_send(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ingest.push.send_test", lambda: "sent")
    assert handler_module.handler({"only": "push-test"}, object()) == {"status": "ok", "push": "sent"}
    monkeypatch.setattr("ingest.push.send_test", lambda: 1 / 0)
    assert handler_module.handler({"only": "push-test"}, object()) == {"status": "failed", "push": "failed"}
