"""Collect items from many sources: parallel fetch, one failing source never sinks the rest, dedupe, filter, sort."""

import random
import re
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, unquote_plus, urlencode, urlsplit, urlunsplit

from ingest.feeds import FeedError, fetch, parse_feed
from ingest.filters import block_reason
from ingest.sources import Source

MAX_AGE = timedelta(hours=72)
MAX_AGE_LOCAL = timedelta(days=7)  # a suburb has few stories a day, so Local keeps a week (its Earlier section shows them)
MAX_FUTURE = timedelta(hours=12)  # a small clock or timezone slip is clamped; more than this is bogus and dropped
MAX_PER_SOURCE = 40
WORKERS = 8
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})  # a busy or rate-limiting server: worth one more try
RETRY_PAUSE_SECONDS = (1.0, 3.0)  # random, so the retried searches do not all land together again
RUN_BUDGET_SECONDS = 40  # whole run; the Lambda timeout is 60 s and the feed must still be written


PUBLISHER_LIMIT = re.compile(r"(?<![-\w])(?:site|inurl|source):")  # not a negated "-site:" or a word such as "website:"


def _scoped_search(url: str) -> bool:
    """A Google News search whose query already names the places, so its items need no place check. A search limited to one
    publisher (`site:`, `inurl:` or `source:`) is not: Google matches the places anywhere in an article, so its results are
    checked like any feed. The cost is that a story whose headline does not name a place is dropped."""
    parts = urlsplit(url)
    return parts.hostname == "news.google.com" and not PUBLISHER_LIMIT.search(unquote_plus(parts.query).lower())


def local_sources(urls: Iterable[str], official: Iterable[str] = ()) -> list[Source]:
    """Sources for the feed URLs in the location parameter. Their items are kept only if they mention a nearby place, except
    for a Google News search that is already scoped to the places. The `official` feeds (a village's or a school district's own)
    are about the place by origin, so every item is kept: list only place-specific feeds there (see the README)."""
    own = [Source(f"local-{i}", _host(u), u, "local", trusted=_scoped_search(u)) for i, u in enumerate(urls)]
    return own + [Source(f"local-official-{i}", _host(u), u, "local", trusted=True) for i, u in enumerate(official)]


def _host(url: str) -> str:
    """A display name for a feed URL: just the host (never userinfo or port)."""
    host = urlsplit(url).hostname
    return re.sub(r"^www\.", "", host) if host else "local"


def _dedupe_key(url: str) -> str:
    """The URL without tracking parameters, fragment and trailing slash, so one story is not shown twice."""
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(("utm_", "fbclid", "gclid"))])
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def _mentions(item: dict[str, Any], pattern: re.Pattern[str]) -> bool:
    """Whether the item names a nearby place. Which one is never recorded: the feed is public and must not say where you live."""
    return pattern.search(f"{item['title']} {item['summary']}") is not None


def collect(
    sources: Iterable[Source],
    nearby: Iterable[str] = (),
    *,
    now: datetime | None = None,
    fetcher: Callable[[str], bytes] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return (items newest first, per-source status). Local items must mention one of `nearby`,
    unless their source is trusted (a search the query already scoped). The place that matched is never recorded."""
    now = now or datetime.now(UTC)
    fetcher = fetcher or fetch  # looked up at call time, so tests can replace the module's fetch
    places = {p for p in nearby if p}
    place_re = re.compile(r"(?<!\w)(" + "|".join(re.escape(p) for p in places) + r")(?!\w)", re.IGNORECASE) if places else None

    def run(source: Source) -> tuple[Source, list[dict[str, Any]], str | None]:
        def once() -> tuple[Source, list[dict[str, Any]], str | None]:
            return source, parse_feed(fetcher(source.url), source), None

        try:
            try:
                return once()
            except FeedError as exc:
                # Google News answers a burst of searches (the local ones run together) with an occasional 429 or 503:
                # one retry after a short random pause usually gets through.
                if urlsplit(source.url).hostname != "news.google.com" or exc.status not in RETRY_STATUSES:
                    raise
                time.sleep(random.uniform(*RETRY_PAUSE_SECONDS))  # noqa: S311  (jitter, not security)
                return once()
        except FeedError as exc:
            return source, [], str(exc)
        except Exception as exc:  # (one bad feed, whatever it raises, must not sink the run)
            return source, [], f"unexpected {type(exc).__name__}"

    sources = [s for s in sources if s.enabled]
    pool = ThreadPoolExecutor(max_workers=WORKERS)
    futures = [(source, pool.submit(run, source)) for source in sources]
    wait([f for _, f in futures], timeout=RUN_BUDGET_SECONDS)
    pool.shutdown(wait=False, cancel_futures=True)  # stragglers are abandoned, not waited for
    results = [f.result() if f.done() else (source, [], "timed out") for source, f in futures]

    items: dict[str, dict[str, Any]] = {}
    by_headline: dict[tuple[str, str], dict[str, Any]] = {}
    status: dict[str, dict[str, Any]] = {}
    for source, parsed, error in results:
        kept = 0
        blocked = 0
        filtered = 0
        only = re.compile(source.only_matching, re.IGNORECASE) if source.only_matching else None
        for item in sorted(parsed, key=lambda i: i["published"], reverse=True):
            if kept >= MAX_PER_SOURCE:  # the cap counts stories that survive the filters, not raw entries
                break
            published = datetime.fromisoformat(item["published"])
            if now - published > (MAX_AGE_LOCAL if source.topic == "local" else MAX_AGE):
                continue
            if published - now > MAX_FUTURE:
                continue
            if published > now:  # a small clock or timezone slip: never show a story from the future
                item["published"] = now.isoformat(timespec="seconds")
            if block_reason(item):
                blocked += 1
                continue
            if source.topic == "local" and not source.trusted and not (place_re and _mentions(item, place_re)):
                continue
            if only and not only.search(f"{item['title']} {item['summary']}"):
                filtered += 1
                continue
            key = _dedupe_key(item["url"])
            same_headline = (item["source"].lower(), item["title"].lower())  # a direct feed and Google News carry one story
            seen = items.get(key) or by_headline.get(same_headline)
            if seen is not None:
                if item.get("subtopic") and not seen.get("subtopic"):
                    seen["subtopic"] = item["subtopic"]  # first seen in a general feed: it still gets the sub-topic tag
                continue
            items[key] = item
            by_headline[same_headline] = item
            kept += 1
        status[source.id] = {
            "ok": error is None,
            "items": kept,
            **({"blocked": blocked} if blocked else {}),
            **({"filtered": filtered} if filtered else {}),
            **({"error": error} if error else {}),
        }
    return sorted(items.values(), key=lambda i: i["published"], reverse=True), status
