"""Collect items from many sources: parallel fetch, one failing source never sinks the rest, dedupe, filter, sort."""

import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ingest.feeds import FeedError, fetch, parse_feed
from ingest.filters import block_reason
from ingest.sources import Source

MAX_AGE = timedelta(hours=72)
MAX_FUTURE = timedelta(hours=12)  # a small clock or timezone slip is clamped; more than this is bogus and dropped
MAX_PER_SOURCE = 40
WORKERS = 8
RUN_BUDGET_SECONDS = 40  # whole run; the Lambda timeout is 60 s and the feed must still be written


def local_sources(urls: Iterable[str]) -> list[Source]:
    """Sources for the feed URLs in the location parameter. Their items are kept only if they mention a nearby place."""
    return [
        Source(id=f"local-{i}", name=_host(url), url=url, topic="local", trusted=urlsplit(url).hostname == "news.google.com")
        for i, url in enumerate(urls)
    ]


def _host(url: str) -> str:
    """A display name for a feed URL: just the host (never userinfo or port)."""
    host = urlsplit(url).hostname
    return re.sub(r"^www\.", "", host) if host else "local"


def _dedupe_key(url: str) -> str:
    """The URL without tracking parameters, fragment and trailing slash, so one story is not shown twice."""
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(("utm_", "fbclid", "gclid"))])
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def _mentions(item: dict[str, Any], pattern: re.Pattern[str], places: dict[str, str]) -> str | None:
    """The configured spelling of the first nearby place the item mentions."""
    found = pattern.search(f"{item['title']} {item['summary']}")
    return places[found.group(0).lower()] if found else None


def collect(
    sources: Iterable[Source],
    nearby: Iterable[str] = (),
    *,
    now: datetime | None = None,
    fetcher: Callable[[str], bytes] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return (items newest first, per-source status). Local items must mention one of `nearby` and get a `place`."""
    now = now or datetime.now(UTC)
    fetcher = fetcher or fetch  # looked up at call time, so tests can replace the module's fetch
    places = {p.lower(): p for p in nearby if p}
    longest_first = sorted(places, key=len, reverse=True)  # "Palatine Heights" must win over "Palatine"
    place_re = (
        re.compile(r"(?<!\w)(" + "|".join(re.escape(p) for p in longest_first) + r")(?!\w)", re.IGNORECASE) if places else None
    )

    def run(source: Source) -> tuple[Source, list[dict[str, Any]], str | None]:
        try:
            return source, parse_feed(fetcher(source.url), source), None
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
    headlines: set[tuple[str, str]] = set()
    status: dict[str, dict[str, Any]] = {}
    for source, parsed, error in results:
        kept = 0
        blocked = 0
        for item in sorted(parsed, key=lambda i: i["published"], reverse=True):
            if kept >= MAX_PER_SOURCE:  # the cap counts stories that survive the filters, not raw entries
                break
            published = datetime.fromisoformat(item["published"])
            if now - published > MAX_AGE:
                continue
            if published - now > MAX_FUTURE:
                continue
            if published > now:  # a small clock or timezone slip: never show a story from the future
                item["published"] = now.isoformat(timespec="seconds")
            if block_reason(item):
                blocked += 1
                continue
            if source.topic == "local":
                place = _mentions(item, place_re, places) if place_re else None
                if not place and not source.trusted:
                    continue
                if place:  # a trusted search (already scoped by its query) keeps items that name no place, unlabelled
                    item["place"] = place
            key = _dedupe_key(item["url"])
            same_headline = (item["source"].lower(), item["title"].lower())  # a direct feed and Google News carry one story
            if key in items or same_headline in headlines:
                continue
            items[key] = item
            headlines.add(same_headline)
            kept += 1
        status[source.id] = {
            "ok": error is None,
            "items": kept,
            **({"blocked": blocked} if blocked else {}),
            **({"error": error} if error else {}),
        }
    return sorted(items.values(), key=lambda i: i["published"], reverse=True), status
