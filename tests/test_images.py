import io
import urllib.request
from typing import Any

import pytest

from ingest import images
from ingest.feeds import parse_feed
from ingest.images import ImageError, attach_images, fetch_image, known_images, sniff
from ingest.sources import Source

SRC = Source("t", "Test", "https://example.com/feed", "us")
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"0" * 100


def feed(entry: str) -> bytes:
    return (
        '<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel><item><title>T</title>'
        f"<link>https://example.com/a</link><pubDate>Fri, 13 Nov 2026 12:00:00 GMT</pubDate>{entry}</item></channel></rss>"
    ).encode()


def image_of(entry: str) -> str | None:
    return parse_feed(feed(entry), SRC)[0].get("_image")


def test_the_widest_picture_wins() -> None:
    entry = (
        '<media:thumbnail url="https://i.example/s.jpg" width="144"/>'
        '<media:content url="https://i.example/l.jpg" medium="image" width="976"/>'
        '<media:content url="https://i.example/v.mp4" medium="video" width="1920"/>'
    )
    assert image_of(entry) == "https://i.example/l.jpg"


def test_enclosures_and_untyped_media_with_an_image_suffix_count() -> None:
    assert image_of('<enclosure url="https://i.example/e.png" type="image/png"/>') == "https://i.example/e.png"
    assert image_of('<enclosure url="https://i.example/a.mp3" type="audio/mpeg"/>') is None
    assert image_of('<media:content url="https://i.example/p.webp"/>') == "https://i.example/p.webp"
    assert image_of('<media:content url="https://i.example/watch"/>') is None


@pytest.mark.parametrize(
    "url", ["http://i.example/a.jpg", "javascript:alert(1)", "https://u:p@i.example/a.jpg", "data:image/png;base64,AA"]
)
def test_only_plain_https_pictures_are_taken(url: str) -> None:
    assert image_of(f'<media:thumbnail url="{url}" width="10"/>') is None


def test_a_bad_width_is_ignored() -> None:
    assert image_of('<media:thumbnail url="https://i.example/a.jpg" width="wide"/>') == "https://i.example/a.jpg"


def test_sniff_judges_by_the_bytes() -> None:
    assert (sniff(JPEG), sniff(PNG), sniff(WEBP)) == ("jpg", "png", "webp")
    assert sniff(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None
    assert sniff(b"GIF89a") is None
    assert sniff(b"") is None


@pytest.fixture
def public(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images, "_is_public", lambda host: True)


class Resp(io.BytesIO):
    def __enter__(self) -> Resp:
        return self

    def __exit__(self, *a: object) -> None:
        return None


def test_fetch_returns_the_bytes_and_extension(monkeypatch: pytest.MonkeyPatch, public: None) -> None:
    monkeypatch.setattr(images._OPENER, "open", lambda req, timeout: Resp(PNG))
    assert fetch_image("https://i.example/a") == (PNG, "png")


def test_fetch_refuses_what_is_not_a_small_public_image(monkeypatch: pytest.MonkeyPatch, public: None) -> None:
    for url in ("http://i.example/a.jpg", "https://u@i.example/a.jpg", "ftp://i.example/a"):
        with pytest.raises(ImageError):
            fetch_image(url)
    monkeypatch.setattr(images._OPENER, "open", lambda req, timeout: Resp(b"<html>nope</html>"))
    with pytest.raises(ImageError, match="not a JPEG"):
        fetch_image("https://i.example/a")
    monkeypatch.setattr(images._OPENER, "open", lambda req, timeout: Resp(JPEG + b"0" * images.MAX_BYTES))
    with pytest.raises(ImageError, match="size cap"):
        fetch_image("https://i.example/a")

    def down(req: Any, timeout: float) -> None:
        raise OSError("boom")

    monkeypatch.setattr(images._OPENER, "open", down)
    with pytest.raises(ImageError, match="fetch failed"):
        fetch_image("https://i.example/a")


def test_fetch_is_too_slow_past_the_deadline(monkeypatch: pytest.MonkeyPatch, public: None) -> None:
    monkeypatch.setattr(images._OPENER, "open", lambda req, timeout: Resp(JPEG))
    clock = iter([0.0, 1000.0, 1000.0])
    monkeypatch.setattr(images.time, "monotonic", lambda: next(clock))
    with pytest.raises(ImageError, match="too slow"):
        fetch_image("https://i.example/a")


def test_private_hosts_and_private_redirects_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images.socket, "getaddrinfo", lambda host, port, type: [(2, 1, 6, "", ("169.254.169.254", 443))])
    with pytest.raises(ImageError, match="public"):
        fetch_image("https://metadata.example/a.jpg")
    monkeypatch.setattr(images.socket, "getaddrinfo", lambda host, port, type: [(2, 1, 6, "", ("93.184.216.34", 443))])
    assert images._is_public("ok.example")

    def fail(host: str, port: int, type: int) -> None:
        raise OSError("no dns")

    monkeypatch.setattr(images.socket, "getaddrinfo", fail)
    assert not images._is_public("nx.example")
    handler = images._CheckedRedirects()
    req = urllib.request.Request("https://i.example/a")
    with pytest.raises(ImageError):
        handler.redirect_request(req, None, 302, "Found", {}, "http://i.example/b")  # type: ignore[arg-type]


class S3:
    def __init__(self, fail: bool = False) -> None:
        self.puts: list[dict[str, Any]] = []
        self.fail = fail

    def put_object(self, **kw: Any) -> None:
        if self.fail:
            raise OSError("denied")
        self.puts.append(kw)


def item(i: str, image: str | None = "https://i.example/x") -> dict[str, Any]:
    return {"id": i, **({"_image": image} if image else {})}


def test_attach_stores_new_pictures_and_reuses_known_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images, "fetch_image", lambda url: (JPEG, "jpg"))
    s3 = S3()
    items = [item("a" * 16), item("b" * 16), item("c" * 16, None)]
    known = {"b" * 16: "b" * 16 + ".png"}
    assert attach_images(s3, "bucket", "data", items, known) == 1
    assert s3.puts == [{"Bucket": "bucket", "Key": f"data/img/{'a' * 16}.jpg", "Body": JPEG, "ContentType": "image/jpeg"}]
    assert items[0]["img"] == "a" * 16 + ".jpg" and items[1]["img"] == "b" * 16 + ".png" and "img" not in items[2]
    assert all("_image" not in i for i in items)


def test_a_failed_download_or_upload_just_means_no_picture(monkeypatch: pytest.MonkeyPatch) -> None:
    def fetch(url: str) -> tuple[bytes, str]:
        if url.endswith("bad"):
            raise ImageError("nope")
        return JPEG, "jpg"

    monkeypatch.setattr(images, "fetch_image", fetch)
    items = [item("a" * 16, "https://i.example/bad"), item("b" * 16)]
    assert attach_images(S3(), "bucket", "data", items, {}) == 1
    assert "img" not in items[0] and items[1]["img"].endswith(".jpg")
    items = [item("a" * 16)]
    assert attach_images(S3(fail=True), "bucket", "data", items, {}) == 0
    assert "img" not in items[0] and "_image" not in items[0]


def test_the_run_is_capped_and_a_slow_download_is_abandoned(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(images, "fetch_image", lambda url: (seen.append(url), (JPEG, "jpg"))[1])
    items = [item(f"{n:016x}", f"https://i.example/{n}") for n in range(images.MAX_PER_RUN + 10)]
    assert attach_images(S3(), "bucket", "data", items, {}) == images.MAX_PER_RUN
    assert len(seen) == images.MAX_PER_RUN and all("img" not in i for i in items[images.MAX_PER_RUN :])
    monkeypatch.setattr(images, "RUN_BUDGET_SECONDS", 0.05)
    monkeypatch.setattr(images, "fetch_image", lambda url: (__import__("time").sleep(0.5), (JPEG, "jpg"))[1])
    slow = [item("d" * 16)]
    assert attach_images(S3(), "bucket", "data", slow, {}) == 0 and "img" not in slow[0]


def test_known_images_ignores_anything_not_our_own_names() -> None:
    ok = {"id": "a" * 16, "img": "a" * 16 + ".webp"}
    bad = [{"id": "b", "img": "../x.jpg"}, {"id": "c", "img": 5}, {"id": 1, "img": "a" * 16 + ".jpg"}, "x", {"id": "d"}]
    assert known_images([ok, *bad]) == {"a" * 16: "a" * 16 + ".webp"}


def test_a_late_run_fetches_nothing_new_but_keeps_what_it_has(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images, "fetch_image", lambda url: pytest.fail("must not fetch"))
    items = [item("a" * 16), item("b" * 16)]
    assert attach_images(S3(), "bucket", "data", items, {"b" * 16: "b" * 16 + ".jpg"}, fetch_new=False) == 0
    assert "img" not in items[0] and items[1]["img"] == "b" * 16 + ".jpg" and "_image" not in items[0]


def test_tiny_pictures_are_not_taken() -> None:
    assert image_of('<media:thumbnail url="https://i.example/pixel.gif" width="1"/>') is None
    assert (
        image_of(
            '<media:thumbnail url="https://i.example/p.jpg" width="1"/>'
            '<media:thumbnail url="https://i.example/q.jpg" width="300"/>'
        )
        == "https://i.example/q.jpg"
    )
