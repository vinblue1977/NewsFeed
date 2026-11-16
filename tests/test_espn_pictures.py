import json

from ingest.espn_pictures import add_pictures, parse_pictures

STORY = "https://www.espn.com/nfl/story/_/id/50495965/kirk-cousins-emotional"


def article(story: str, images: list) -> dict:
    return {"links": {"web": {"href": story}}, "images": images}


def photo(width: int, url: str = "https://a.espncdn.com/photo/2026/1115/r1_{w}.jpg") -> dict:
    return {"width": width, "url": url.format(w=width)}


def doc(*articles: dict) -> bytes:
    return json.dumps({"articles": list(articles)}).encode()


def test_parse_pictures_picks_the_widest_real_photo() -> None:
    got = parse_pictures(
        doc(article(STORY, [photo(300), photo(1296), photo(608), {"width": 900, "url": "https://s.espncdn.com/x.png"}]))
    )
    assert got == {"50495965": "https://a.espncdn.com/photo/2026/1115/r1_1296.jpg"}


def test_parse_pictures_skips_what_it_cannot_use() -> None:
    odd = [
        article(STORY, [photo(200)]),  # too small
        article(STORY, [{"width": 900, "url": "http://a.espncdn.com/photo/x.jpg"}]),  # not https
        article(STORY, [{"width": "900", "url": "https://a.espncdn.com/photo/x.jpg"}, "nope", {"url": 5, "width": 900}]),
        article("https://www.espn.com/nfl/", [photo(900)]),  # no story id
        {"links": None},
        "nope",
    ]
    assert parse_pictures(doc(*odd)) == {}
    for bad in (b"not json", b"{}", b'{"articles": 5}', b"[]"):
        assert parse_pictures(bad) == {}


def test_add_pictures_sets_only_matching_espn_nfl_items() -> None:
    items = [
        {"source_id": "espn-nfl", "url": STORY},
        {"source_id": "espn-nfl", "url": "https://www.espn.com/nfl/story/_/id/1/other"},
        {"source_id": "espn-nfl", "url": STORY, "_image": "https://x.test/own.jpg"},
        {"source_id": "bbc-tennis", "url": STORY},
    ]
    assert add_pictures(items, lambda _url: doc(article(STORY, [photo(608)]))) == 1
    assert items[0]["_image"].endswith("r1_608.jpg")
    assert "_image" not in items[1]
    assert items[2]["_image"] == "https://x.test/own.jpg"
    assert "_image" not in items[3]


def test_add_pictures_is_fail_soft() -> None:
    def boom(_url: str) -> bytes:
        raise OSError("down")

    items = [{"source_id": "espn-nfl", "url": STORY}]
    assert add_pictures(items, boom) == 0
    assert add_pictures([{"source_id": "bbc-tennis", "url": STORY}], boom) == 0  # nothing wanted: no request at all
