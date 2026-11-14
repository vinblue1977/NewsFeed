import http.client
import io
import urllib.error
import urllib.request
from typing import Any

import pytest

from ingest import feeds
from ingest.feeds import FeedError, clean_text, fetch, parse_feed
from ingest.sources import SOURCES, Source

SRC = Source("t", "Test News", "https://example.com/feed", "us")

RSS = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
<item><title>First &amp; best</title><link>https://example.com/a</link>
<description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&amp;nbsp;again&lt;/p&gt;</description>
<pubDate>Fri, 13 Nov 2026 12:00:00 GMT</pubDate></item>
<item><title>Dated by dc</title><link>https://example.com/b</link><dc:date>2026-11-13T10:00:00Z</dc:date></item>
<item><title>Bad link</title><link>javascript:alert(1)</link><pubDate>Fri, 13 Nov 2026 12:00:00 GMT</pubDate></item>
<item><title></title><link>https://example.com/c</link><pubDate>Fri, 13 Nov 2026 12:00:00 GMT</pubDate></item>
<item><title>No date</title><link>https://example.com/d</link></item>
<item><title>Garbage date</title><link>https://example.com/e</link><pubDate>someday</pubDate></item>
<item><title>Guid link</title><guid>https://example.com/g</guid><pubDate>Fri, 13 Nov 2026 12:00:00</pubDate></item>
</channel></rss>"""

ATOM_FEED = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Atom story</title><link rel="self" href="https://example.com/self"/><link rel="alternate" href="https://example.com/x"/>
<summary>Short</summary><updated>2026-11-13T09:00:00+02:00</updated></entry>
<entry><title>Only link</title><link href="https://example.com/y"/><published>2026-11-13T09:00:00Z</published>
<summary>Only link</summary></entry>
<entry><title>No link</title><updated>2026-11-13T09:00:00Z</updated></entry>
</feed>"""


def test_parse_rss_normalises_and_drops_bad_items() -> None:
    items = parse_feed(RSS, SRC)
    assert [i["url"] for i in items] == ["https://example.com/a", "https://example.com/b", "https://example.com/g"]
    first = items[0]
    assert first["title"] == "First & best"
    assert first["summary"] == "Hello world again"
    assert first["published"] == "2026-11-13T12:00:00+00:00"
    assert first["source"] == "Test News" and first["topic"] == "us"
    assert len(first["id"]) == 16
    assert items[1]["published"] == "2026-11-13T10:00:00+00:00"  # dc:date fallback
    assert items[2]["published"] == "2026-11-13T12:00:00+00:00"  # naive date assumed UTC


def test_parse_atom_prefers_the_alternate_link_and_converts_to_utc() -> None:
    items = parse_feed(ATOM_FEED, SRC)
    assert [i["url"] for i in items] == ["https://example.com/x", "https://example.com/y"]
    assert items[0]["published"] == "2026-11-13T07:00:00+00:00"
    assert items[1]["summary"] == ""  # a summary that repeats the title is dropped


def test_subtopic_and_metered_flags_are_carried() -> None:
    src = Source("t", "T", "https://example.com/f", "sports", "nfl", metered=True)
    item = parse_feed(RSS, src)[0]
    assert item["subtopic"] == "nfl" and item["metered"] is True


@pytest.mark.parametrize(
    "body",
    [
        b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaa">]><rss><channel/></rss>',
        b"<rss><channel><item><title>&x;</title></item></channel></rss><!ENTITY x 'y'>",
        b"<rss><unclosed>",
        b"not xml at all",
    ],
)
def test_parse_rejects_hostile_or_broken_documents(body: bytes) -> None:
    with pytest.raises(FeedError):
        parse_feed(body, SRC)


def test_clean_text() -> None:
    assert clean_text(None) == "" and clean_text("") == ""
    assert clean_text("<script>evil()</script><style>p{}</style>a   b\n c") == "a b c"
    long = clean_text("word " * 200, 50)
    assert len(long) <= 51 and long.endswith("…")


class FakeResponse(io.BytesIO):
    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class FakeOpener:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.requests: list[Any] = []

    def open(self, request: Any, timeout: int) -> Any:
        self.requests.append((request, timeout))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_fetch_returns_the_body(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = FakeOpener(FakeResponse(b"<rss/>"))
    monkeypatch.setattr(feeds, "_OPENER", opener)
    assert fetch("https://example.com/f") == b"<rss/>"
    request, timeout = opener.requests[0]
    assert timeout == feeds.TIMEOUT_SECONDS and "NewsPWA" in request.get_header("User-agent")


def test_fetch_refuses_non_https() -> None:
    for url in ("http://example.com/f", "file:///etc/passwd", "ftp://example.com/f"):
        with pytest.raises(FeedError, match="https"):
            fetch(url)


@pytest.mark.parametrize("error", [urllib.error.URLError("down"), TimeoutError(), http.client.IncompleteRead(b"x")])
def test_fetch_wraps_network_errors(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    monkeypatch.setattr(feeds, "_OPENER", FakeOpener(error))
    with pytest.raises(FeedError, match="fetch failed"):
        fetch("https://example.com/f")


def test_fetch_enforces_the_size_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feeds, "MAX_BYTES", 10)
    monkeypatch.setattr(feeds, "_OPENER", FakeOpener(FakeResponse(b"x" * 100)))
    with pytest.raises(FeedError, match="size cap"):
        fetch("https://example.com/f")


def test_fetch_enforces_a_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feeds, "DEADLINE_SECONDS", -1)
    monkeypatch.setattr(feeds, "_OPENER", FakeOpener(FakeResponse(b"x" * 100)))
    with pytest.raises(FeedError, match="too slow"):
        fetch("https://example.com/f")


def test_redirects_must_stay_on_https() -> None:
    handler = feeds._HttpsOnlyRedirects()
    request = urllib.request.Request("https://example.com/f")
    with pytest.raises(FeedError, match="non-https"):
        handler.redirect_request(request, io.BytesIO(), 302, "Found", {}, "http://example.com/plain")
    assert handler.redirect_request(request, io.BytesIO(), 302, "Found", {}, "https://example.com/g") is not None


@pytest.mark.parametrize(
    "body",
    [
        "<?xml version='1.0'?><!DOCTYPE x [<!ENTITY a 'b'>]><rss/>".encode("utf-16"),  # BOM + NULs
        "<?xml version='1.0'?><!DOCTYPE x><rss/>".encode("utf-16-le"),  # NULs, no BOM
        b"<?xml version='1.0' encoding='UTF-32'?><rss/>",
        b"<?xml version='1.0' encoding='utf-8'?><rss><a/>" + b" " * 9000 + b"<!DOCTYPE late></rss>",  # past the first 4 KB
    ],
)
def test_parse_rejects_encodings_and_late_doctypes_the_scan_cannot_see(body: bytes) -> None:
    with pytest.raises(FeedError):
        parse_feed(body, SRC)


def test_parse_accepts_declared_latin1() -> None:
    xml = (
        "<?xml version='1.0' encoding='ISO-8859-1'?><rss><channel><item><title>Café</title><link>https://e.com/a</link>"
        "<pubDate>Fri, 13 Nov 2026 12:00:00 GMT</pubDate></item></channel></rss>"
    )
    body = xml.encode("latin-1")
    assert parse_feed(body, SRC)[0]["title"] == "Café"


def test_source_list_is_sane() -> None:
    ids = [s.id for s in SOURCES]
    assert len(ids) == len(set(ids))
    assert all(s.url.startswith("https://") for s in SOURCES)
    assert {s.topic for s in SOURCES} == {"us", "world", "india", "sports", "tech", "business"}
    headline_only = {s.id for s in SOURCES if s.headline_only}
    assert headline_only == {"gn-ap", "gn-cnn", "gn-reuters"}
    assert all("news.google.com" in s.url for s in SOURCES if s.id in headline_only)
    assert {s.subtopic for s in SOURCES if s.topic == "sports"} == {"nfl", "cricket", "tennis"}


ITEM = "<item><title>T</title><link>https://e.com/a</link><pubDate>Fri, 13 Nov 2026 12:00:00 GMT</pubDate>{extra}</item>"


def test_html_inside_cdata_or_comments_is_not_a_doctype() -> None:
    extra = "<description><![CDATA[<!DOCTYPE html><p>hi</p> <!ENTITY x>]]></description><!-- <!DOCTYPE y> -->"
    body = f"<rss><channel>{ITEM.format(extra=extra)}</channel></rss>".encode()
    assert len(parse_feed(body, SRC)) == 1


@pytest.mark.parametrize("encoding", ["latin1", "ISO-8859-15", "windows-1251", "utf8", "US-ASCII"])
def test_common_declared_encodings_are_accepted(encoding: str) -> None:
    body = f"<?xml version='1.0' encoding='{encoding}'?><rss><channel>{ITEM.format(extra='')}</channel></rss>".encode()
    assert len(parse_feed(body, SRC)) == 1


def test_a_utf8_bom_and_a_late_declaration_are_handled() -> None:
    plain = f"<?xml version='1.0' encoding='UTF-8'?><rss><channel>{ITEM.format(extra='')}</channel></rss>".encode()
    assert len(parse_feed(b"\xef\xbb\xbf" + plain, SRC)) == 1
    bad = b"\xef\xbb\xbf<?xml version='1.0' encoding='UTF-16'?><rss/>"
    with pytest.raises(FeedError, match="encoding"):
        parse_feed(bad, SRC)


def test_out_of_range_dates_drop_the_item_not_the_feed() -> None:
    items = [
        ITEM.format(extra="").replace("Fri, 13 Nov 2026 12:00:00 GMT", "Fri, 31 Dec 9999 23:00:00 -1400"),
        ITEM.format(extra="").replace("https://e.com/a", "https://e.com/b"),
    ]
    got = parse_feed(f"<rss><channel>{''.join(items)}</channel></rss>".encode(), SRC)
    assert [i["url"] for i in got] == ["https://e.com/b"]


def test_atom_xhtml_summary_and_padded_values() -> None:
    body = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title> Padded </title>
    <link href="https://e.com/x"/><updated>2026-11-13T09:00:00Z</updated>
    <summary type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml">Hello <b>there</b></div></summary></entry></feed>"""
    item = parse_feed(body, SRC)[0]
    assert item["title"] == "Padded" and item["summary"] == "Hello there"


GNEWS = b"""<rss><channel>
<item><title>Flights grounded across US - Reuters</title><link>https://news.google.com/rss/articles/CBM1?oc=5</link>
<description>&lt;a href="x"&gt;Flights grounded across US&lt;/a&gt;&amp;nbsp;&lt;font&gt;Reuters&lt;/font&gt;</description>
<pubDate>Fri, 13 Nov 2026 12:00:00 GMT</pubDate><source url="https://www.reuters.com">Reuters</source></item>
<item><title>Palatine police charge man - Journal &amp;amp; Topics</title><link>https://news.google.com/rss/articles/CBM2?oc=5</link>
<pubDate>Fri, 13 Nov 2026 11:00:00 GMT</pubDate>
<source url="https://www.journal-topics.com">Journal &amp;amp; Topics</source></item>
</channel></rss>"""


def test_google_news_items_use_the_real_publisher_and_are_headline_only() -> None:
    src = Source("gn", "Reuters", "https://news.google.com/rss/search?q=x", "world", headline_only=True)
    first, second = parse_feed(GNEWS, src)
    assert first["title"] == "Flights grounded across US"  # the " - Reuters" tail is dropped
    assert first["source"] == "Reuters" and first["domain"] == "reuters.com" and first["summary"] == ""
    assert second["title"] == "Palatine police charge man" and second["source"] == "Journal & Topics"
    assert second["domain"] == "journal-topics.com"


def test_plain_items_get_their_link_host_as_domain() -> None:
    assert parse_feed(RSS, SRC)[0]["domain"] == "example.com"


def test_a_source_element_in_an_ordinary_feed_does_not_rename_the_publisher() -> None:
    body = (
        b"<rss><channel><item><title>Story - Feed Title</title><link>https://news.example.com/a</link>"
        b'<pubDate>Fri, 13 Nov 2026 12:00:00 GMT</pubDate><source url="https://other.example/feed.xml">Feed Title</source>'
        b"</item></channel></rss>"
    )
    item = parse_feed(body, SRC)[0]
    assert item["source"] == "Test News" and item["domain"] == "news.example.com" and item["title"] == "Story - Feed Title"


def test_google_news_item_without_a_source_element_falls_back_to_the_queried_site() -> None:
    body = (
        b"<rss><channel><item><title>Flights grounded</title><link>https://news.google.com/rss/articles/X</link>"
        b"<pubDate>Fri, 13 Nov 2026 12:00:00 GMT</pubDate></item></channel></rss>"
    )
    src = Source("gn", "Reuters", "https://news.google.com/rss/search?q=x", "world", headline_only=True, site="reuters.com")
    assert parse_feed(body, src)[0]["domain"] == "reuters.com"
    unknown = Source("gl", "g", "https://news.google.com/rss/search?q=x", "local", trusted=True)
    assert parse_feed(body, unknown)[0]["domain"] == "news.google.com"
