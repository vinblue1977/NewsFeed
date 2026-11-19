"""Pictures for stories whose feed names none (NFL.com's sitemap, local feeds): the story page's own og:image.

Only new stories are looked at, newest first, a few per run; a page that cannot be read, or whose picture is the site's
generic placeholder, simply stays without one. The page and what it names are untrusted."""

import logging
import re
from collections import Counter
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from ingest.feeds import fetch
from ingest.images import fetch_page_head

logger = logging.getLogger()

SOURCE_ID = "nfl-com"
PICTURE_HOST = "static.www.nfl.com"
PLACEHOLDER_ALT = "fallback-athletic"  # nfl.com's stand-in when a story has no photo of its own
MAX_PAGES_PER_RUN = 8  # NFL.com pages; local stories get as many again
WORKERS = 2 * MAX_PAGES_PER_RUN  # one wave: every page at once
RUN_BUDGET_SECONDS = 7
PAGE_DEADLINE_SECONDS = 5
HEAD_BYTES = 200_000  # the meta tags are in the head; the rest of the page is not read
RECENT = timedelta(hours=6)  # a page with no usable picture is looked at again each run, so only stories this new are tried
HEAD_END = re.compile(r"</head\s*>", re.IGNORECASE)


class _Meta(HTMLParser):
    """Collects the first og:image and og:image:alt (property names in any case)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        meta = dict(attrs)
        name = (meta.get("property") or meta.get("name") or "").lower()
        if name in ("og:image", "og:image:alt") and meta.get("content"):
            self.found.setdefault(name, str(meta["content"]))


def og_image(page: bytes, any_host: bool = False) -> str | None:
    """The story's own picture URL, or None: no og:image, an http one, the placeholder, or (unless `any_host`, used for local
    publishers whose picture host is not known in advance) one not on the NFL.com picture host. The picture itself is
    fetched later with full URL checks (public https host only, JPEG/PNG/WebP, size cap)."""
    head = HEAD_END.split(page[:HEAD_BYTES].decode("utf-8", errors="replace"), maxsplit=1)[0]
    parser = _Meta()
    try:
        parser.feed(head)
    except Exception:  # noqa: BLE001  (a malformed page is just a page without a picture)
        return None
    url = parser.found.get("og:image")
    if not url or parser.found.get("og:image:alt") == PLACEHOLDER_ALT:
        return None
    parts = urlsplit(url)
    return url if parts.scheme == "https" and (any_host or parts.netloc == PICTURE_HOST) else None


def _is_local(item: dict[str, Any]) -> bool:
    """A local story that links straight to its publisher. Google News links are redirects, not pages with a picture."""
    return item.get("topic") == "local" and urlsplit(item.get("url", "")).hostname not in (None, "news.google.com")


def _get(url: str) -> bytes:
    return fetch(url, accept="text/html", deadline_seconds=PAGE_DEADLINE_SECONDS, head_bytes=HEAD_BYTES)


def _get_local(url: str) -> bytes:
    return fetch_page_head(url, PAGE_DEADLINE_SECONDS, HEAD_BYTES)  # untrusted host: public https only, redirects checked


def _look(get: Callable[[str], bytes], item: dict[str, Any], local: bool) -> str | None:
    return og_image(get(item["url"]), any_host=local)


def add_page_pictures(
    items: list[dict[str, Any]],
    known: Mapping[str, str] | None = None,
    getter: Callable[[str], bytes] | None = None,
    now: datetime | None = None,
) -> int:
    """Set the private `_image` of recent NFL.com and local stories that have no picture yet.
    `known` is the stories that already have a stored one (they are not looked at again).
    Fail-soft: any trouble means no picture, never an error."""
    have = known or {}
    cutoff = (now or datetime.now(UTC)) - RECENT
    fresh = [
        i
        for i in items
        if not i.get("_image")
        and i["id"] not in have
        and datetime.fromisoformat(i.get("published", "1970-01-01T00:00:00+00:00")) >= cutoff
    ]
    fresh.sort(key=lambda i: i.get("published", ""), reverse=True)  # newest first
    nfl = [i for i in fresh if i.get("source_id") == SOURCE_ID][:MAX_PAGES_PER_RUN]
    local = [i for i in fresh if i.get("source_id") != SOURCE_ID and _is_local(i)][:MAX_PAGES_PER_RUN]
    wanted = nfl + local
    local_ids = {i["id"] for i in local}
    if not wanted:
        return 0
    get_nfl = getter or _get
    get_local = getter or _get_local
    pool = ThreadPoolExecutor(max_workers=WORKERS)
    futures = {
        i["id"]: pool.submit(_look, get_local if i["id"] in local_ids else get_nfl, i, i["id"] in local_ids) for i in wanted
    }
    wait(list(futures.values()), timeout=RUN_BUDGET_SECONDS)
    pool.shutdown(wait=False, cancel_futures=True)  # a stalled page is abandoned, not waited for
    found: dict[str, str] = {}
    for item in wanted:
        future = futures[item["id"]]
        try:
            url = future.result() if future.done() else None
        except Exception:  # noqa: BLE001  (one bad page must not cost the others)
            url = None
        if url:
            found[item["id"]] = url
    shared = Counter(u for k, u in found.items() if k in local_ids)
    added = 0
    for item in wanted:
        url = found.get(item["id"])
        if url and not (item["id"] in local_ids and shared[url] > 1):  # one picture on several stories is a site logo
            item["_image"] = url
            added += 1
    logger.info("page pictures (nfl.com, local): %d of %d pages gave one", added, len(wanted))
    return added
