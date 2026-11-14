import json
import time
from email.utils import formatdate
from typing import Any

import boto3
import pytest

from ingest import articles as articles_module
from ingest import handler as handler_module
from ingest.articles import MAX_ARTICLES, MAX_CHARS, MIN_CHARS, build_articles, dumps, html_to_blocks
from ingest.feeds import parse_feed
from ingest.sources import Source

SRC = Source("t", "Test News", "https://example.com/feed", "us")
PARA = "This is a sentence of plain prose that repeats to fill a paragraph. " * 4  # about 260 characters


def body(paragraphs: int = 4) -> str:
    return "".join(f"<p>{PARA}</p>" for _ in range(paragraphs))


def item(id: str, html: str | None, published: str = "2026-11-13T12:00:00+00:00", **extra: Any) -> dict[str, Any]:  # noqa: A002
    out: dict[str, Any] = {"id": id, "title": id, "published": published, **extra}
    if html is not None:
        out["_html"] = html
    return out


def run(items: list[dict[str, Any]], generated: str = "g") -> tuple[dict[str, Any], set[str]]:
    """build_articles as the handler calls it: the HTML travels in a side dict, not on the items."""
    bodies = {i["id"]: i.pop("_html") for i in items if "_html" in i}
    return build_articles(items, bodies, generated)


# --- HTML -> blocks -------------------------------------------------------------------------------------------------


def test_blocks_keep_paragraphs_headings_lists_and_quotes_as_plain_text() -> None:
    html = (
        "<h1>Big</h1><p>One &amp; <b>two</b> <a href='https://x.example'>links</a>.</p>"
        "<h3>Small</h3><ul><li>first</li><li>second <em>item</em></li></ul>"
        "<blockquote><p>quoted words</p></blockquote><p>after</p>"
    )
    assert html_to_blocks(html) == [
        {"t": "h", "x": "Big"},
        {"t": "p", "x": "One & two links."},
        {"t": "h", "x": "Small"},
        {"t": "li", "x": "first"},
        {"t": "li", "x": "second item"},
        {"t": "q", "x": "quoted words"},
        {"t": "p", "x": "after"},
    ]


def test_blocks_drop_scripts_media_embeds_tables_and_forms() -> None:
    html = (
        "<p>keep</p><script>alert(1)</script><style>p{}</style><iframe src='https://evil.example'>fallback</iframe>"
        "<figure><img src='x.png' onerror='alert(1)'><figcaption>caption</figcaption></figure>"
        "<table><tr><td>cell</td></tr></table><form><button>Buy</button></form><svg><text>vector</text></svg>"
        "<noscript>enable js</noscript><a href='javascript:alert(1)'>click</a><p>and keep</p>"
    )
    blocks = html_to_blocks(html)
    assert [b["x"] for b in blocks] == ["keep", "click", "and keep"]  # a link's text is kept, its target never
    assert "javascript" not in json.dumps(blocks) and "<" not in json.dumps(blocks)


def test_blocks_collapse_whitespace_drop_empty_blocks_and_strip_control_characters() -> None:
    assert html_to_blocks("<p>  a \n\t b​ </p><p> </p><p></p><p>x\x00y</p>") == [{"t": "p", "x": "a b"}, {"t": "p", "x": "xy"}]


def test_blocks_treat_bare_text_and_br_as_paragraphs() -> None:
    assert html_to_blocks("first<br><br>second<div>third</div>") == [
        {"t": "p", "x": "first"},
        {"t": "p", "x": "second"},
        {"t": "p", "x": "third"},
    ]


def test_blocks_drop_the_wordpress_link_back_line() -> None:
    html = "<p>Real text.</p><p>The post Some Title appeared first on Some Site.</p>"
    assert html_to_blocks(html) == [{"t": "p", "x": "Real text."}]


def test_a_void_embed_does_not_swallow_the_rest_of_the_article() -> None:
    html = "<p>before</p><embed src='x'><object><param name='a'></object><p>after the embed</p>"
    assert [b["x"] for b in html_to_blocks(html)] == ["before", "after the embed"]


def test_a_paragraph_inside_a_list_item_quote_or_heading_keeps_the_outer_kind() -> None:
    assert html_to_blocks("<ul><li><p>item one</p></li><li>item two</li></ul>") == [
        {"t": "li", "x": "item one"},
        {"t": "li", "x": "item two"},
    ]
    assert html_to_blocks("<blockquote><p>said</p><p>more</p></blockquote><h2><p>Head</p></h2><p>plain</p>") == [
        {"t": "q", "x": "said"},
        {"t": "q", "x": "more"},
        {"t": "h", "x": "Head"},
        {"t": "p", "x": "plain"},
    ]


def test_nested_skipped_elements_close_with_their_own_end_tag() -> None:
    assert [
        b["x"] for b in html_to_blocks("<table><tr><td><table><tr><td>x</td></tr></table>still</td></tr></table><p>ok</p>")
    ] == ["ok"]


def test_blocks_survive_unclosed_stray_and_nested_markup() -> None:
    assert html_to_blocks("<p>one<p>two</div></span></blockquote><b><i>three") == [
        {"t": "p", "x": "one"},
        {"t": "p", "x": "two"},
        {"t": "p", "x": "three"},
    ]
    assert html_to_blocks("<script>never closed <p>hidden</p>") == []  # an unclosed script swallows the rest, safely
    assert html_to_blocks("</script></table></blockquote><p>ok</p>") == [{"t": "p", "x": "ok"}]


def test_blocks_handle_hostile_and_huge_input_quickly() -> None:
    nasty = "<div>" * 50_000 + "<<<<a <a <a href=" * 20_000 + "&#" * 20_000 + "<!--" + "x" * 300_000
    start = time.monotonic()
    blocks = html_to_blocks(nasty)
    assert time.monotonic() - start < 5
    assert isinstance(blocks, list)
    assert (
        html_to_blocks("<p>" + "word " * 100_000)[0]["x"].count("word") <= articles_module.MAX_INPUT_CHARS // 5
    )  # cut before parsing


def test_blocks_of_nothing_and_of_a_parser_failure_are_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    assert html_to_blocks(None) == [] and html_to_blocks("") == []

    def boom(self: Any, data: str) -> None:
        raise AssertionError("bad markup")

    monkeypatch.setattr(articles_module._Blocks, "feed", boom)
    assert html_to_blocks("<p>x</p>") == []


# --- the budget -----------------------------------------------------------------------------------------------------


def test_an_article_needs_at_least_the_minimum_amount_of_text() -> None:
    short = f"<p>{'x' * (MIN_CHARS - 1)}</p>"
    enough = f"<p>{'x' * MIN_CHARS}</p>"
    doc, ids = run([item("short", short), item("enough", enough)], "g")
    assert ids == {"enough"} and set(doc["articles"]) == {"enough"} and doc["generated"] == "g"


def test_each_article_is_cut_at_a_block_boundary() -> None:
    paragraphs = MAX_CHARS // len(PARA) + 5
    doc, _ = run([item("long", body(paragraphs))], "g")
    blocks = doc["articles"]["long"]
    assert sum(len(b["x"]) for b in blocks) <= MAX_CHARS
    assert all(b["x"] == PARA.strip() for b in blocks)  # whole paragraphs only; the rest is dropped
    assert 0 < len(blocks) < paragraphs


def test_one_huge_block_is_cut_at_a_word_with_an_ellipsis() -> None:
    doc, _ = run([item("wall", f"<p>{'word ' * 5000}</p>")], "g")
    (block,) = doc["articles"]["wall"]
    assert block["x"].endswith("word…") and len(block["x"]) <= MAX_CHARS + 1


def test_newest_articles_win_the_article_cap() -> None:
    items = [
        item(f"a{n:03d}", body(), published=f"2026-11-13T{n // 60:02d}:{n % 60:02d}:00+00:00") for n in range(MAX_ARTICLES + 10)
    ]
    doc, ids = run(items, "g")
    assert len(ids) == MAX_ARTICLES
    assert "a069" in ids and "a010" in ids and "a009" not in ids  # the ten oldest are left out
    assert list(doc["articles"])[0] == "a069"  # newest first


def test_the_whole_document_stays_under_its_byte_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(articles_module, "MAX_BYTES", 3000)
    items = [item(f"b{n}", body(), published=f"2026-11-13T12:0{n}:00+00:00") for n in range(6)]
    doc, ids = run(items, "g")
    assert 0 < len(ids) < 6 and ids == set(doc["articles"])
    assert len(json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode()) <= 3000
    assert "b5" in ids  # the newest are the ones kept


def test_metered_and_bodyless_items_are_left_out() -> None:
    doc, ids = run([item("m", body(), metered=True), item("none", None), item("ok", body())], "g")
    assert ids == {"ok"} and set(doc["articles"]) == {"ok"}


def test_no_items_gives_an_empty_document() -> None:
    assert run([]) == ({"generated": "g", "articles": {}}, set())


# --- parse_feed keeps the body ---------------------------------------------------------------------------------------

LONG = "".join(f"<p>{PARA}</p>" for _ in range(3))


def rss_item(extra: str) -> bytes:
    xml = (
        '<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><item><title>T</title>'
        "<link>https://e.com/a</link><pubDate>Fri, 13 Nov 2026 12:00:00 GMT</pubDate>" + extra + "</item></channel></rss>"
    )
    return xml.encode()


def test_parse_feed_keeps_content_encoded() -> None:
    (parsed,) = parse_feed(
        rss_item(f"<description>short</description><content:encoded><![CDATA[{LONG}]]></content:encoded>"), SRC
    )
    assert parsed["_html"] == LONG and parsed["summary"] == "short"


def test_parse_feed_keeps_a_long_description() -> None:
    (parsed,) = parse_feed(rss_item(f"<description><![CDATA[{LONG}]]></description>"), SRC)
    assert parsed["_html"] == LONG


def test_parse_feed_keeps_atom_content() -> None:
    xml = (
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>T</title><link href="https://e.com/a"/>'
        "<published>2026-11-13T12:00:00Z</published><summary>s</summary>"
        f'<content type="html"><![CDATA[{LONG}]]></content></entry></feed>'
    )
    (parsed,) = parse_feed(xml.encode(), SRC)
    assert parsed["_html"] == LONG


def test_parse_feed_keeps_the_paragraphs_of_atom_xhtml_content() -> None:
    xml = (
        '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:h="http://www.w3.org/1999/xhtml"><entry><title>T</title>'
        '<link href="https://e.com/a"/><published>2026-11-13T12:00:00Z</published><content type="xhtml"><h:div>'
        + "".join(f"<h:p>{PARA} &amp; <h:b>bold</h:b> tail</h:p>" for _ in range(3))
        + "</h:div></content></entry></feed>"
    )
    (parsed,) = parse_feed(xml.encode(), SRC)
    blocks = html_to_blocks(parsed["_html"])
    assert len(blocks) == 3 and all(b["x"].endswith("& bold tail") for b in blocks)  # three paragraphs, not one run-on


def test_a_pathologically_deep_xhtml_body_falls_back_to_its_text(monkeypatch: pytest.MonkeyPatch) -> None:
    from ingest import feeds as feeds_module

    def too_deep(element: Any) -> str:
        raise RecursionError

    monkeypatch.setattr(feeds_module, "_inner_html", too_deep)
    xml = (
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>T</title><link href="https://e.com/a"/>'
        f'<published>2026-11-13T12:00:00Z</published><content type="xhtml"><div><p>{PARA * 3}</p></div></content></entry></feed>'
    )
    (parsed,) = parse_feed(xml.encode(), SRC)
    assert parsed["_html"].startswith("This is a sentence")


def test_parse_feed_ignores_teasers_metered_headline_only_and_google_news() -> None:
    assert "_html" not in parse_feed(rss_item("<description>tiny</description>"), SRC)[0]
    full = f"<description><![CDATA[{LONG}]]></description>"
    metered = Source("m", "M", "https://e.com/f", "us", metered=True)
    headline = Source("h", "H", "https://e.com/f", "us", headline_only=True)
    assert "_html" not in parse_feed(rss_item(full), metered)[0]
    assert "_html" not in parse_feed(rss_item(full), headline)[0]
    google = rss_item(full).replace(b"https://e.com/a", b"https://news.google.com/rss/articles/x")
    assert "_html" not in parse_feed(google, SRC)[0]


def test_parse_feed_caps_a_huge_body() -> None:
    (parsed,) = parse_feed(rss_item(f"<description><![CDATA[{'x' * 500_000}]]></description>"), SRC)
    assert len(parsed["_html"]) == articles_module.MAX_INPUT_CHARS


# --- the handler ----------------------------------------------------------------------------------------------------


class S3:
    def __init__(self, fail: str | None = None) -> None:
        self.puts: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self.fail = fail

    def put_object(self, **kw: Any) -> None:
        if self.fail and kw["Key"].endswith(self.fail):
            raise OSError("denied")
        self.puts[kw["Key"]] = kw
        self.order.append(kw["Key"])

    def get_object(self, **kw: Any) -> None:
        raise OSError("no previous feed")


def feed_with_full_text(url: str) -> bytes:
    """A feed whose one entry carries the whole article and was published an hour ago (the handler uses the real clock)."""
    hour_ago = formatdate(time.time() - 3600, usegmt=True).encode()
    xml = rss_item(f"<description><![CDATA[{LONG}]]></description>")
    return xml.replace(b"https://e.com/a", url.encode() + b"/a").replace(b"Fri, 13 Nov 2026 12:00:00 GMT", hour_ago)


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    monkeypatch.setenv("DATA_PREFIX", "data")
    monkeypatch.setattr(handler_module, "cached_location", lambda: {"nearby": [], "feeds": [], "lat": 40.0, "lon": -90.0})
    monkeypatch.setattr(handler_module, "SOURCES", (Source("a", "A", "https://a.example/f", "us"),))
    monkeypatch.setattr("ingest.pipeline.fetch", lambda url: feed_with_full_text("https://a.example"))

    def down(*args: Any) -> dict[str, Any]:
        raise RuntimeError("down")

    for name in ("build_weather", "build_markets", "build_scores"):
        monkeypatch.setattr(handler_module, name, down)


def test_handler_writes_articles_then_the_feed_and_flags_only_written_articles(
    monkeypatch: pytest.MonkeyPatch, setup: None
) -> None:
    s3 = S3()
    monkeypatch.setattr(boto3, "client", lambda name: s3)
    result = handler_module.handler({}, object())
    assert result["articles"] == "ok"
    assert s3.order.index("data/articles.json") < s3.order.index("data/feed.json")  # the text is there before the flag
    feed = json.loads(s3.puts["data/feed.json"]["Body"])
    articles = json.loads(s3.puts["data/articles.json"]["Body"])
    assert s3.puts["data/articles.json"]["ContentType"] == "application/json"
    flagged = {i["id"] for i in feed["items"] if i.get("full")}
    assert flagged and flagged == set(articles["articles"])
    assert all("_html" not in i for i in feed["items"])  # the raw HTML never reaches feed.json
    assert "<" not in json.dumps(articles)


def test_the_articles_file_and_the_feed_share_one_generated_stamp_and_one_encoding(
    monkeypatch: pytest.MonkeyPatch, setup: None
) -> None:
    s3 = S3()
    monkeypatch.setattr(boto3, "client", lambda name: s3)
    handler_module.handler({}, object())
    feed = json.loads(s3.puts["data/feed.json"]["Body"])
    articles = json.loads(s3.puts["data/articles.json"]["Body"])
    assert feed["generated"] == articles["generated"]  # a page can tell that its two files belong together
    assert dumps({"t": "é"}) == '{"t":"é"}'.encode() and s3.puts["data/feed.json"]["Body"] == dumps(feed)


def test_handler_drops_the_flags_when_articles_cannot_be_written(monkeypatch: pytest.MonkeyPatch, setup: None) -> None:
    s3 = S3(fail="articles.json")
    monkeypatch.setattr(boto3, "client", lambda name: s3)
    result = handler_module.handler({}, object())
    assert result["articles"] == "failed" and result["status"] == "ok"
    feed = json.loads(s3.puts["data/feed.json"]["Body"])
    assert feed["items"] and all("full" not in i for i in feed["items"])


def test_handler_writes_a_flagless_feed_when_the_articles_step_fails(monkeypatch: pytest.MonkeyPatch, setup: None) -> None:
    s3 = S3()
    monkeypatch.setattr(boto3, "client", lambda name: s3)

    def boom(items: Any, bodies: Any, generated: str) -> None:
        for i in items:
            i["full"] = True  # even if it fails half way, no flag survives
        raise ValueError("bad body")

    monkeypatch.setattr(handler_module, "build_articles", boom)
    result = handler_module.handler({}, object())
    assert result["articles"] == "failed" and "data/articles.json" not in s3.puts
    feed = json.loads(s3.puts["data/feed.json"]["Body"])
    assert feed["items"] and all("full" not in i and "_html" not in i for i in feed["items"])


def test_a_rejected_feed_run_writes_no_articles(monkeypatch: pytest.MonkeyPatch, setup: None) -> None:
    s3 = S3()
    monkeypatch.setattr(boto3, "client", lambda name: s3)
    monkeypatch.setattr("ingest.pipeline.fetch", lambda url: (_ for _ in ()).throw(OSError("down")))
    with pytest.raises(RuntimeError, match="keeping the previous feed"):
        handler_module.handler({}, object())
    assert "data/articles.json" not in s3.puts and "data/feed.json" not in s3.puts
