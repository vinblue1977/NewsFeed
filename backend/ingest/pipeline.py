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
from ingest.sources import POLITICS_RE, Source

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


def local_sources(urls: Iterable[str], official: Iterable[str] = (), alerts: Iterable[str] = ()) -> list[Source]:
    """Sources for the feed URLs in the location parameter. Their items are kept only if they mention a nearby place, except
    for a Google News search that is already scoped to the places. The `official` feeds (a village's or a school district's own)
    are about the place by origin, so every item is kept: list only place-specific feeds there (see the README). The `alerts`
    feeds are the same, and their items are also marked so the push step can send each one (once)."""
    own = [Source(f"local-{i}", _host(u), u, "local", trusted=_scoped_search(u)) for i, u in enumerate(urls)]
    given = [
        Source(f"local-official-{i}", _host(u), u, "local", trusted=True, news_only=_is_google_news(u))
        for i, u in enumerate(official)
    ]
    pushed = [
        Source(f"local-alert-{i}", _host(u), u, "local", trusted=True, alert=True, news_only=_is_google_news(u))
        for i, u in enumerate(alerts)
    ]
    return own + given + pushed


_WORD = re.compile(r"[^\W\d_][\w'’]*")  # a word starts with a letter, so "2", "3" and "102" alone are not words


def headline_like(item: dict[str, Any]) -> bool:
    """Whether the title reads as a news headline and not a web page's title. A Google News search of one site returns the site's
    pages too: "Home | Tripp Elementary School", "District 102", or just the site name. Looking at the part before any "|" (the
    usual page-title separator, also used as "Headline | Publisher"), a headline has three or more words once the site's name
    is taken out."""
    head = item["title"].split("|", 1)[0]
    source = item.get("source", "")
    if source:
        head = re.sub(re.escape(source), "", head, flags=re.IGNORECASE)
    return len(_WORD.findall(head)) >= 3


def _is_google_news(url: str) -> bool:
    return urlsplit(url).hostname == "news.google.com"


def _host(url: str) -> str:
    """A display name for a feed URL: just the host (never userinfo or port)."""
    host = urlsplit(url).hostname
    return re.sub(r"^www\.", "", host) if host else "local"


_SITE = re.compile(r"(?<![-\w])site:([a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)")  # not a "-site:" exclusion; the host only, no path


def status_name(source: Source) -> str:
    """What Settings > Source health calls a feed. A national feed: its name. A local feed: its host, or for a Google News
    search the one publisher it is limited to ("dailyherald.com (Google News)"). Never the rest of the query: that is where the
    nearby places are. `collect` publishes a local feed's name only when the feed produced stories, see there."""
    if source.topic != "local" or not _is_google_news(source.url):
        return source.name
    site = _SITE.search(unquote_plus(urlsplit(source.url).query).lower())
    return f"{site.group(1)} (Google News)" if site else "Google News search"


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

    politics = re.compile(POLITICS_RE, re.IGNORECASE)
    items: dict[str, dict[str, Any]] = {}
    by_headline: dict[tuple[str, str], dict[str, Any]] = {}
    status: dict[str, dict[str, Any]] = {}
    for source, parsed, error in results:
        kept = 0
        blocked = 0
        filtered = 0
        duplicates = 0
        only = re.compile(source.only_matching, re.IGNORECASE) if source.only_matching else None
        skip = re.compile(source.skip_path, re.IGNORECASE) if source.skip_path else None
        skip_title = re.compile(source.skip_title) if source.skip_title else None  # case-sensitive on purpose
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
            if source.news_only and not headline_like(item):
                filtered += 1
                continue
            if skip and skip.search(urlsplit(item["url"]).path):  # counted as "filtered", like news_only and only_matching
                filtered += 1
                continue
            if skip_title and skip_title.search(item["title"]):
                filtered += 1
                continue
            if only and not only.search(f"{item['title']} {item['summary']}"):
                filtered += 1
                continue
            if source.topic == "us" and not item.get("subtopic") and politics.search(item["title"]):
                item["subtopic"] = "politics"  # a politics story from a general US feed still lands in the politics sections
            key = _dedupe_key(item["url"])
            same_headline = (item["source"].lower(), item["title"].lower())  # a direct feed and Google News carry one story
            seen = items.get(key) or by_headline.get(same_headline)
            if seen is not None:
                if item.get("subtopic") and not seen.get("subtopic"):
                    seen["subtopic"] = item["subtopic"]  # first seen in a general feed: it still gets the sub-topic tag
                if source.alert:
                    seen["_alert"] = True  # the village's own alert for a story another feed carried first is still an alert
                duplicates += 1  # fetched fine, but another feed had the story first: Settings must not call this feed empty
                continue
            if source.alert:
                item["_alert"] = True  # private: build_feed takes it off again before anything is written
            items[key] = item
            by_headline[same_headline] = item
            kept += 1
        status[source.id] = {
            # A local feed is named only when it produced stories: that name already shows on them. A silent local feed's host
            # (a village or school site) could give away the town, so it stays unnamed and Settings shows its position instead.
            **({"name": status_name(source)} if source.topic != "local" or kept else {}),
            "ok": error is None,
            "items": kept,
            **({"blocked": blocked} if blocked else {}),
            **({"filtered": filtered} if filtered else {}),
            **({"duplicates": duplicates} if duplicates else {}),
            **({"error": error} if error else {}),
        }
    return sorted(items.values(), key=lambda i: i["published"], reverse=True), status
