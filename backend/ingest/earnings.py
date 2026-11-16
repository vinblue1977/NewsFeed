"""Upcoming earnings dates for the watchlist symbols, from Finnhub's earnings calendar (one request per symbol).

The key comes from SSM and travels in a request header, never in a URL. Everything fails soft: a symbol that cannot be read
is skipped, and only when none could be read does the build raise, so the previous file stays. Symbols come from the private
watchlist: the result is written only to the private file, never to the public feed."""

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote

from ingest.feeds import fetch

CALENDAR_URL = "https://finnhub.io/api/v1/calendar/earnings?from={start}&to={end}&symbol={symbol}"
DAYS_AHEAD = 60  # the app shows the next two weeks on Markets, and any date on a symbol's own page
WORKERS = 6
WAIT_SECONDS = 15  # a hard cap on all the symbols together
DEADLINE_SECONDS = 8
REFRESH_HOURS = 6  # the dates rarely move; this keeps the calls to a few a day
TIMES = {"bmo": "pre", "amc": "post"}  # before market open, after market close; anything else is not announced


class EarningsError(Exception):
    """No symbol could be read, or an answer was not usable."""


def askable(symbol: str) -> bool:
    """Indexes (^GSPC) and futures or currencies (CL=F, EURUSD=X) have no earnings; asking would only spend calls."""
    return bool(symbol) and not symbol.startswith("^") and "=" not in symbol


def finnhub_symbol(symbol: str) -> str:
    """Yahoo writes a share class BRK-B; Finnhub writes BRK.B."""
    return symbol.upper().replace("-", ".")


def parse_symbol(body: bytes, symbol: str, today: date) -> dict[str, Any] | None:
    """The symbol's next report (today or later) from Finnhub's answer, or None when it has none in the window. Raises
    EarningsError when the answer is not the calendar's shape."""
    try:
        rows = json.loads(body)["earningsCalendar"] or []
        found = []
        for row in rows:
            day = date.fromisoformat(row["date"])
            if day >= today:
                eps = row.get("epsEstimate")
                found.append(
                    {
                        "symbol": symbol,
                        "date": day.isoformat(),
                        "time": TIMES.get(row.get("hour"), "tbd"),
                        "eps": float(eps) if isinstance(eps, int | float) and not isinstance(eps, bool) else None,
                    }
                )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise EarningsError(f"not usable ({type(exc).__name__})") from exc
    return min(found, key=lambda i: i["date"]) if found else None


def build_earnings(
    symbols: list[str], token: str, *, today: date | None = None, getter: Callable[[str], bytes] | None = None
) -> dict[str, Any]:
    """{"generated", "symbols", "items"}: each symbol's next report within DAYS_AHEAD days, soonest first. Raises EarningsError
    when no symbol could be read."""
    start = today or datetime.now(UTC).date() - timedelta(
        days=1
    )  # a day back: the US date can trail UTC; the app shows from its own today
    get = getter or (
        lambda url: fetch(url, accept="application/json", deadline_seconds=DEADLINE_SECONDS, headers={"X-Finnhub-Token": token})
    )
    asked = [s for s in dict.fromkeys(symbols) if askable(s)]
    window = {"start": start.isoformat(), "end": (start + timedelta(days=DAYS_AHEAD)).isoformat()}
    pool = ThreadPoolExecutor(max_workers=WORKERS)
    try:
        futures = {
            s: pool.submit(
                lambda s=s: parse_symbol(get(CALENDAR_URL.format(**window, symbol=quote(finnhub_symbol(s), safe=""))), s, start)
            )
            for s in asked
        }
        wait(list(futures.values()), timeout=WAIT_SECONDS)
        read = {s: f.result() for s, f in futures.items() if f.done() and f.exception() is None}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # a stalled request is abandoned, not waited for
    if asked and not read:
        raise EarningsError("no symbol could be read; keeping the previous file")
    items = sorted((i for i in read.values() if i), key=lambda i: (i["date"], i["symbol"]))
    unread = {s for s in asked if s not in read}  # not listed as covered, so the next run asks about them again
    covered = sorted(s for s in symbols if s not in unread)
    return {"generated": datetime.now(UTC).isoformat(timespec="seconds"), "symbols": covered, "items": items}


def is_due(previous: Any, symbols: list[str], now: datetime | None = None) -> bool:
    """Whether the earnings file needs rebuilding: there is none, it is older than REFRESH_HOURS, or the watchlist changed."""
    try:
        age = (now or datetime.now(UTC)) - datetime.fromisoformat(previous["generated"])
        return age > timedelta(hours=REFRESH_HOURS) or sorted(previous["symbols"]) != sorted(symbols)
    except KeyError, TypeError, ValueError:
        return True
