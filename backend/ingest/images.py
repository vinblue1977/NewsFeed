"""Story pictures: download the image a feed names, check it really is one, and store it in our own bucket.

The app never loads an image from a publisher (its CSP allows only its own origin); it shows these copies instead.
Everything here treats the feed's image URL, and what it points at, as untrusted."""

import http.client
import ipaddress
import logging
import re
import socket
import time
import urllib.request
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger()

USER_AGENT = "Mozilla/5.0 (compatible; NewsPWA/1.0; personal reader)"
TIMEOUT_SECONDS = 6
DEADLINE_SECONDS = 8  # per image, the socket timeout alone resets on every byte
MAX_BYTES = 300_000  # bigger pictures are skipped: they cost phone data, and a phone screen needs far less
MAX_PER_RUN = 30  # new pictures fetched in one run; a failing URL cannot use up the run
RUN_BUDGET_SECONDS = 12  # all downloads of one run together
WORKERS = 6
IMG_DIR = "img"  # under the data prefix, which CloudFront already serves
NAME = re.compile(r"^[0-9a-f]{16}\.(jpg|png|webp)$")


class ImageError(Exception):
    """An image could not be fetched or is not acceptable."""


def _is_public(host: str) -> bool:
    """True if every address the host resolves to is a public one (no loopback, private, link-local or metadata address)."""
    try:
        found = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return False
    return bool(found) and all(ipaddress.ip_address(f[4][0]).is_global for f in found)


def _check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or "@" in parts.netloc:
        raise ImageError("only plain https image URLs are fetched")
    if not _is_public(parts.hostname):
        raise ImageError("the image host is not a public address")


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        _check_url(newurl)  # every hop gets the same checks as the first URL
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_CheckedRedirects)


def sniff(body: bytes) -> str | None:
    """The file extension for a JPEG, PNG or WebP (judged by the bytes, never by what the server says), else None."""
    if body.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "webp"
    return None


def fetch_image(url: str) -> tuple[bytes, str]:
    """The image bytes and extension. Raises ImageError for anything unusual; nothing else escapes."""
    _check_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/jpeg,image/png,image/webp"})  # noqa: S310  (https checked above)
    deadline = time.monotonic() + DEADLINE_SECONDS
    body = bytearray()
    try:
        with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
            while chunk := response.read(8192):
                body += chunk
                if len(body) > MAX_BYTES:
                    raise ImageError("image is larger than the size cap")
                if time.monotonic() > deadline:
                    raise ImageError("image is too slow")
    except (OSError, http.client.HTTPException) as exc:
        raise ImageError(f"fetch failed: {type(exc).__name__}") from exc
    ext = sniff(bytes(body))
    if ext is None:
        raise ImageError("not a JPEG, PNG or WebP image")
    return bytes(body), ext


def known_images(items: Iterable[Any]) -> dict[str, str]:
    """item id -> image file name from the feed written last time. Anything not shaped like our own names is ignored."""
    out: dict[str, str] = {}
    for i in items:
        if isinstance(i, dict) and isinstance(i.get("id"), str) and isinstance(i.get("img"), str) and NAME.match(i["img"]):
            out[i["id"]] = i["img"]
    return out


def attach_images(
    s3: Any, bucket: str, prefix: str, items: list[dict[str, Any]], known: dict[str, str], *, fetch_new: bool = True
) -> int:
    """Give each item its `img` file name: reuse last run's, or fetch and store new ones (newest first, at most MAX_PER_RUN).
    `fetch_new=False` (the run is already late) only reuses what exists. Removes the private `_image` URL from every item.
    Fail-soft: a story without a picture is simply shown without one."""
    wanted = [i for i in items if i["id"] not in known and i.get("_image")][:MAX_PER_RUN] if fetch_new else []
    pool = ThreadPoolExecutor(max_workers=WORKERS)
    futures = {i["id"]: pool.submit(fetch_image, i["_image"]) for i in wanted}
    wait(list(futures.values()), timeout=RUN_BUDGET_SECONDS)
    pool.shutdown(wait=False, cancel_futures=True)  # stragglers are abandoned, not waited for
    stored = 0
    new: dict[str, str] = {}
    for item_id, future in futures.items():
        try:
            if not future.done():
                continue
            body, ext = future.result()
            name = f"{item_id}.{ext}"
            s3.put_object(
                Bucket=bucket,
                Key=f"{prefix}/{IMG_DIR}/{name}",
                Body=body,
                ContentType={"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[ext],
            )
            new[item_id] = name
            stored += 1
        except Exception as exc:  # noqa: BLE001  (one bad picture must not cost the others or the feed)
            logger.info("no picture for %s: %s", item_id, type(exc).__name__)
    for item in items:
        item.pop("_image", None)
        name = known.get(item["id"]) or new.get(item["id"])
        if name:
            item["img"] = name
    return stored
