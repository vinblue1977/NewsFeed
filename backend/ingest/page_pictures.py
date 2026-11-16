"""Pictures for stories whose feed names none (NFL.com's sitemap has no images): the story page's own og:image.

Only new stories are looked at, newest first, a few per run; a page that cannot be read, or whose picture is the site's
generic placeholder, simply stays without one. The page and what it names are untrusted."""

import logging
import re
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from ingest.feeds import fetch

logger = logging.getLogger()

SOURCE_ID = "nfl-com"
PICTURE_HOST = "static.www.nfl.com"
PLACEHOLDER_ALT = "fallback-athletic"  # nfl.com's stand-in when a story has no photo of its own
MAX_PAGES_PER_RUN = 8
WORKERS = MAX_PAGES_PER_RUN  # one wave: every page at once
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


def og_image(page: bytes) -> str | None:
    """The story's own picture URL, or None: no og:image, an http or foreign-host one, or the placeholder."""
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
    return url if parts.scheme == "https" and parts.netloc == PICTURE_HOST else None


def _get(url: str) -> bytes:
    return fetch(url, accept="text/html", deadline_seconds=PAGE_DEADLINE_SECONDS, head_bytes=HEAD_BYTES)


def add_page_pictures(
    items: list[dict[str, Any]],
    known: Mapping[str, str] | None = None,
    getter: Callable[[str], bytes] | None = None,
    now: datetime | None = None,
) -> int:
    """Set the private `_image` of recent NFL.com stories that have no picture yet. `known` is the stories that already have a
    stored one (they are not looked at again). Fail-soft: any trouble means no picture, never an error."""
    have = known or {}
    cutoff = (now or datetime.now(UTC)) - RECENT
    wanted = [
        i
        for i in items
        if i.get("source_id") == SOURCE_ID
        and not i.get("_image")
        and i["id"] not in have
        and datetime.fromisoformat(i.get("published", "1970-01-01T00:00:00+00:00")) >= cutoff
    ][:MAX_PAGES_PER_RUN]
    if not wanted:
        return 0
    get = getter or _get
    pool = ThreadPoolExecutor(max_workers=WORKERS)
    futures = {i["id"]: pool.submit(lambda u=i["url"]: og_image(get(u))) for i in wanted}
    wait(list(futures.values()), timeout=RUN_BUDGET_SECONDS)
    pool.shutdown(wait=False, cancel_futures=True)  # a stalled page is abandoned, not waited for
    added = 0
    for item in wanted:
        future = futures[item["id"]]
        try:
            url = future.result() if future.done() else None
        except Exception:  # noqa: BLE001  (one bad page must not cost the others)
            url = None
        if url:
            item["_image"] = url
            added += 1
    logger.info("nfl.com pictures: %d of %d pages gave one", added, len(wanted))
    return added
