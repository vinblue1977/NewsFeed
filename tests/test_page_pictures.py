import time
from datetime import UTC, datetime

from ingest import page_pictures
from ingest.feeds import parse_feed
from ingest.page_pictures import add_page_pictures, og_image
from ingest.sources import Source

SOURCE = Source(
    "nfl-com", "NFL.com", "https://www.nfl.com/sitemap-fast-changing.xml", "sports", "nfl", headline_only=True, sitemap=True
)
IMG = "https://static.www.nfl.com/image/upload/t_editorial_landscape_12_desktop/league/abc"


def entry(
    path: str, title: str = "A headline", date: str = "2026-11-15T11:31:08Z", news: bool = True, host: str = "www.nfl.com"
) -> str:
    block = (
        f"<news:news><news:publication><news:name>NFL.com</news:name></news:publication>"
        f"<news:publication_date>{date}</news:publication_date><news:title>{title}</news:title></news:news>"
        if news
        else ""
    )
    return f"<url><loc>https://{host}{path}</loc><lastmod>{date}</lastmod>{block}</url>"


def sitemap(*entries: str) -> bytes:
    ns = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"'
    return f"<urlset {ns}>{''.join(entries)}</urlset>".encode()


def test_sitemap_gives_headline_stories_of_the_source_host_only() -> None:
    body = sitemap(
        entry("/news/lions-win", "Lions win &amp; how"),
        entry("/news/no-block", news=False),
        entry("/videos/clip", "A video"),
        entry("/news/other-host", host="evil.example.com"),
        entry("/news/no-date", date="not a date"),
        entry("/news/no-title", title=""),
    )
    got = parse_feed(body, SOURCE)
    assert [(i["url"], i["title"], i["summary"], i["subtopic"], i["source_id"]) for i in got] == [
        ("https://www.nfl.com/news/lions-win", "Lions win & how", "", "nfl", "nfl-com")
    ]
    assert got[0]["published"] == "2026-11-15T11:31:08+00:00"
    assert got[0]["domain"] == "nfl.com"
    apex = parse_feed(sitemap(entry("/news/x", host="NFL.com")), SOURCE)  # the apex domain, any case, is still the source's host
    assert [i["url"] for i in apex] == ["https://NFL.com/news/x"]
    assert "_image" not in got[0]


def page(image: str | None, alt: str | None = None, head_end: bool = True) -> bytes:
    meta = (f'<meta property="og:image" content="{image}"/>' if image else "") + (
        f'<meta property="og:image:alt" content="{alt}"/>' if alt else ""
    )
    end = "</head>" if head_end else ""
    late = f'<body><meta property="og:image" content="{IMG}z"/></body>'  # after the head: only read when the head never ends
    return f"<html><head><title>x</title>{meta}{end}{late}</html>".encode()


def test_og_image_takes_a_real_https_photo_from_the_picture_host() -> None:
    assert og_image(page(IMG, "Baker Mayfield tn")) == IMG
    assert og_image(page(IMG)) == IMG


def test_og_image_reads_tags_in_any_case_and_stops_at_the_head() -> None:
    upper = f'<HTML><HEAD><META PROPERTY="OG:IMAGE" CONTENT="{IMG}"/></HEAD><BODY></BODY></HTML>'.encode()
    assert og_image(upper) == IMG
    assert og_image(page(None, "tn")) is None  # an alt with no picture


def test_og_image_skips_the_placeholder_and_anything_untrusted() -> None:
    assert og_image(page(IMG, "fallback-athletic")) is None
    assert og_image(page(None)) is None
    assert og_image(page("http://static.www.nfl.com/a.jpg")) is None
    assert og_image(page("https://evil.example.com/a.jpg")) is None
    assert og_image(b"\xff\xfe not html at all <meta") is None
    assert og_image(page(None, head_end=False)) == IMG + "z"  # no </head>: the page is read as given


NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
FRESH = "2026-11-15T11:00:00+00:00"


def items() -> list[dict]:
    return [
        {"id": "a", "source_id": "nfl-com", "url": "https://www.nfl.com/news/a", "published": FRESH},
        {"id": "b", "source_id": "nfl-com", "url": "https://www.nfl.com/news/b", "published": FRESH},
        {
            "id": "c",
            "source_id": "nfl-com",
            "url": "https://www.nfl.com/news/c",
            "published": FRESH,
            "_image": "https://x.test/own.jpg",
        },
        {"id": "d", "source_id": "espn-nfl", "url": "https://www.espn.com/nfl/story/_/id/1/x", "published": FRESH},
    ]


def test_add_page_pictures_looks_only_at_new_nfl_stories() -> None:
    seen: list[str] = []

    def get(url: str) -> bytes:
        seen.append(url)
        return page(IMG, "tn") if url.endswith("/a") else page(IMG, "fallback-athletic")

    rows = items()
    assert add_page_pictures(rows, {"b": "b.jpg"}, get, NOW) == 1
    assert seen == ["https://www.nfl.com/news/a"]  # b is already stored, c already has one, d is not NFL.com
    assert rows[0]["_image"] == IMG
    assert "_image" not in rows[1]
    assert rows[2]["_image"] == "https://x.test/own.jpg"
    assert "_image" not in rows[3]


def test_add_page_pictures_is_fail_soft_and_capped() -> None:
    def boom(_url: str) -> bytes:
        raise OSError("down")

    rows = items()
    assert add_page_pictures(rows, None, boom, NOW) == 0
    assert add_page_pictures([{"id": "d", "source_id": "espn-nfl", "url": "u"}], None, boom) == 0  # nothing wanted: no request
    many = [{"id": str(n), "source_id": "nfl-com", "url": f"https://www.nfl.com/news/{n}", "published": FRESH} for n in range(20)]
    calls: list[str] = []

    def get(url: str) -> bytes:
        calls.append(url)
        return page(IMG, "tn")

    assert add_page_pictures(many, None, get, NOW) == 8
    assert len(calls) == 8


def test_add_page_pictures_skips_old_stories_and_gives_up_on_a_stalled_page(monkeypatch) -> None:
    old = {"id": "o", "source_id": "nfl-com", "url": "https://www.nfl.com/news/o", "published": "2026-11-14T11:00:00+00:00"}
    calls: list[str] = []

    def get(url: str) -> bytes:
        calls.append(url)
        return page(IMG, "tn")

    assert add_page_pictures([old], None, get, NOW) == 0
    assert calls == []  # a day old: not looked at

    monkeypatch.setattr(page_pictures, "RUN_BUDGET_SECONDS", 0.05)

    def slow(_url: str) -> bytes:
        time.sleep(0.5)
        return page(IMG, "tn")

    fresh = {"id": "n", "source_id": "nfl-com", "url": "https://www.nfl.com/news/n", "published": FRESH}
    assert add_page_pictures([fresh], None, slow, NOW) == 0
    assert "_image" not in fresh
