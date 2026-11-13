"""Collect items from many sources: parallel fetch, one failing source never sinks the rest, dedupe, filter, sort."""

import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

from ingest.feeds import FeedError, fetch, parse_feed
from ingest.sources import Source

MAX_AGE = timedelta(hours=72)
MAX_PER_SOURCE = 40
WORKERS = 8


def local_sources(urls: Iterable[str]) -> list[Source]:
    """Sources for the feed URLs in the location parameter. Their items are kept only if they mention a nearby place."""
    return [Source(id=f"local-{i}", name=_host(url), url=url, topic="local") for i, url in enumerate(urls)]


def _host(url: str) -> str:
    return re.sub(r"^www\.", "", url.split("/")[2]) if url.count("/") >= 2 else url


def _mentions(item: dict[str, Any], pattern: re.Pattern[str]) -> str | None:
    found = pattern.search(f"{item['title']} {item['summary']}")
    return found.group(0) if found else None


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
    places = [p for p in nearby if p]
    place_re = re.compile(r"\b(" + "|".join(re.escape(p) for p in places) + r")\b", re.IGNORECASE) if places else None

    def run(source: Source) -> tuple[Source, list[dict[str, Any]], str | None]:
        try:
            return source, parse_feed(fetcher(source.url), source), None
        except FeedError as exc:
            return source, [], str(exc)

    sources = [s for s in sources if s.enabled]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(run, sources))

    items: dict[str, dict[str, Any]] = {}
    status: dict[str, dict[str, Any]] = {}
    for source, parsed, error in results:
        kept = 0
        for item in sorted(parsed, key=lambda i: i["published"], reverse=True)[:MAX_PER_SOURCE]:
            published = datetime.fromisoformat(item["published"])
            if now - published > MAX_AGE:
                continue
            if published > now:  # a feed with a clock or timezone slip: never show a story from the future
                item["published"] = now.isoformat(timespec="seconds")
            if source.topic == "local":
                place = _mentions(item, place_re) if place_re else None
                if not place:
                    continue
                item["place"] = place.title()
            if item["url"] in items:
                continue
            items[item["url"]] = item
            kept += 1
        status[source.id] = {"ok": error is None, "items": kept, **({"error": error} if error else {})}
    return sorted(items.values(), key=lambda i: i["published"], reverse=True), status
