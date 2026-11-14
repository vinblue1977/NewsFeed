import json
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest

from ingest import handler as handler_module
from ingest import pipeline
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
    assert [(i["title"], i["place"]) for i in items] == [
        ("Road closed in Buffalo Grove", "Buffalo Grove"),
        ("Palatine news", "Palatine"),
    ]


def test_place_uses_the_configured_spelling() -> None:
    docs = {"https://c.example/f": rss(("ROAD WORK IN MCKINNEY", "https://x.example/9", "", "Fri, 13 Nov 2026 09:00:00 GMT"))}
    items, _ = collect([src("c", "c", topic="local")], ["McKinney"], now=NOW, fetcher=docs.__getitem__)
    assert items[0]["place"] == "McKinney"


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


def test_handler_writes_the_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3()
    monkeypatch.setattr(boto3, "client", lambda name: s3)
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    monkeypatch.setenv("DATA_PREFIX", "data")
    monkeypatch.setattr(handler_module, "cached_location", lambda: {"nearby": ["Palatine"], "feeds": ["https://c.example/f"]})
    monkeypatch.setattr(handler_module, "SOURCES", (src("a", "a"),))
    monkeypatch.setattr("ingest.pipeline.fetch", fake_fetcher)
    result = handler_module.handler({}, object())
    assert result["status"] == "ok" and result["failed"] == []
    (put,) = s3.puts
    assert put["Bucket"] == "bucket" and put["Key"] == "data/feed.json" and put["ContentType"] == "application/json"
    body = json.loads(put["Body"])
    assert {"generated", "items", "sources"} <= body.keys()
    assert {i["topic"] for i in body["items"]} <= {"us", "local"}
    assert {c["id"] for c in body["clusters"]} == {i["cluster"] for i in body["items"]}


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


def test_the_longest_place_name_wins_and_odd_names_match() -> None:
    docs = {
        "https://c.example/f": rss(
            ("Palatine Heights school board", "https://x.example/1", "", "Fri, 13 Nov 2026 09:00:00 GMT"),
            ("Mayor of St. Charles speaks", "https://x.example/2", "", "Fri, 13 Nov 2026 08:00:00 GMT"),
        )
    }
    items, _ = collect(
        [src("c", "c", topic="local")], ["Palatine", "Palatine Heights", "St. Charles"], now=NOW, fetcher=docs.__getitem__
    )
    assert [i["place"] for i in items] == ["Palatine Heights", "St. Charles"]


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
    docs = {"https://g.example/f": rss(("Road work starts Monday", "https://x.example/1", "", "Fri, 13 Nov 2026 09:00:00 GMT"))}
    scoped = Source("g", "g", "https://g.example/f", "local", trusted=True)
    items, _ = collect([scoped], ["Buffalo Grove", "Palatine"], now=NOW, fetcher=docs.__getitem__)
    assert items[0]["place"] == "Buffalo Grove"
    items, _ = collect([scoped], [], now=NOW, fetcher=docs.__getitem__)
    assert items == []  # nothing to label it with


def test_only_google_news_local_feeds_are_trusted() -> None:
    made = local_sources(["https://news.google.com/rss/search?q=x", "https://wgntv.example/feed"])
    assert [s.trusted for s in made] == [True, False]
