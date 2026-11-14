"""Market quotes for data/markets.json: the index strip plus an optional watchlist, from Yahoo Finance's chart endpoint.

The endpoint is unofficial and has no terms or SLA, so everything here fails soft: a symbol that cannot be read is reported
with `ok: false` and never sinks the others. Only when fewer than half of the symbols could be read does the build raise, so the
previous file stays in place instead of being replaced by a mostly empty one.

`open` is a snapshot taken when the file is built (inside the regular session and traded in the last 30 minutes), so it can
be up to one ingest interval out of date. `last_trade` (UTC, ISO) is the time of the last trade, so a client can judge
freshness itself."""

import json
import math
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from ingest.config import MAX_TICKERS, SYMBOL
from ingest.feeds import USER_AGENT, FeedError, clean_text, fetch

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart"
JSON_ACCEPT = "application/json"
INDEXES = ("^GSPC", "^IXIC", "^DJI", "^NSEI", "^BSESN")
SERIES_POINTS = 40  # sparklines need no more than this
WAIT_SECONDS = 8  # a hard cap on the whole fetch; the socket timeout alone can run longer than the fetch deadline
DEADLINE_SECONDS = 6
MAX_WORKERS = len(INDEXES) + MAX_TICKERS  # one worker per symbol, so no symbol waits in a queue for a slot
RECENT_TRADE_SECONDS = 30 * 60  # the last trade must be this recent for the market to count as open


class MarketsError(Exception):
    """No quote could be read at all."""


def _num(value: Any, places: int = 2) -> float | None:
    """A finite number, or None (JSON gives null for gaps, and a bad value must not reach the page)."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return round(float(value), places)


def chart_url(symbol: str) -> str:
    return f"{YAHOO_CHART}/{quote(symbol, safe='')}?interval=5m&range=1d"


def downsample(values: list[float], points: int = SERIES_POINTS) -> list[float]:
    """At most `points` values spread evenly across the series, always keeping the first and the last."""
    if len(values) <= points:
        return values
    step = (len(values) - 1) / (points - 1)
    return [values[round(i * step)] for i in range(points)]


def _iso(timestamp: float | None) -> str | None:
    """A Unix time as an ISO UTC string, or None if it is missing or out of range."""
    if timestamp is None or timestamp <= 0:  # Yahoo sends 0 for an instrument with no trades: that is "unknown", not 1970
        return None
    try:
        return datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="seconds")
    except OverflowError, OSError, ValueError:
        return None


def parse_quote(symbol: str, body: bytes, now: datetime) -> dict[str, Any]:
    """Yahoo chart JSON -> one quote. Raises MarketsError if it has no usable price."""
    try:
        result = json.loads(body)["chart"]["result"][0]
        meta = result["meta"]
        price = _num(meta["regularMarketPrice"])
        prev = _num(meta["chartPreviousClose"] if meta.get("chartPreviousClose") is not None else meta.get("previousClose"))
        closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        period = (meta.get("currentTradingPeriod") or {}).get("regular") or {}  # null for some instruments (crypto, FX, funds)
        start, end = _num(period.get("start"), 0), _num(period.get("end"), 0)
        traded = _num(meta.get("regularMarketTime"), 0)
        name = clean_text(meta.get("shortName") or meta.get("longName"), 60)
        currency = clean_text(meta.get("currency"), 8)
        series = [v for v in (_num(c) for c in closes) if v is not None]
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        raise MarketsError(f"{symbol}: quote is not usable ({type(exc).__name__})") from exc
    if price is None:
        raise MarketsError(f"{symbol}: no price")
    change = round(price - prev, 2) if prev else None
    return {
        "symbol": symbol,
        "name": name or symbol,
        "ok": True,
        "price": price,
        "prev_close": prev,
        "change": change,
        "change_pct": round(change / prev * 100, 2) if change is not None and prev else None,
        "currency": currency,
        "last_trade": _iso(traded),
        # open = inside the regular session AND traded recently (on an exchange holiday the session window still looks current,
        # but the last trade is from the previous day)
        "open": start is not None
        and end is not None
        and traded is not None
        and start <= now.timestamp() <= end
        and 0 <= now.timestamp() - traded <= RECENT_TRADE_SECONDS,
        "series": downsample(series),
    }


def _fetch_quote(symbol: str, now: datetime, get: Any) -> dict[str, Any]:
    try:
        return parse_quote(symbol, get(chart_url(symbol)), now)
    except FeedError, MarketsError:
        return {"symbol": symbol, "ok": False}


def build_markets(tickers: list[str] | None = None, *, getter: Any = None, now: datetime | None = None) -> dict[str, Any]:
    """The markets document: {"generated", "indexes": [...], "tickers": [...]}. Raises MarketsError if nothing could be read."""
    now = now or datetime.now(UTC)
    get = getter or (lambda url: fetch(url, accept=JSON_ACCEPT, deadline_seconds=DEADLINE_SECONDS, user_agent=USER_AGENT))
    # Case-insensitive, and an index named in the watchlist is not shown twice (it is already in the strip).
    extra = [t for t in dict.fromkeys(t.upper() for t in tickers or []) if SYMBOL.fullmatch(t) and t not in INDEXES]
    symbols = [*INDEXES, *extra]
    pool = ThreadPoolExecutor(max_workers=min(len(symbols), MAX_WORKERS))
    try:
        futures = {s: pool.submit(_fetch_quote, s, now, get) for s in symbols}
        wait(futures.values(), timeout=WAIT_SECONDS)
        quotes = {s: f.result() if f.done() else {"symbol": s, "ok": False} for s, f in futures.items()}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # a stalled request is abandoned, not waited for
    good = sum(q["ok"] for q in quotes.values())
    if good * 2 < len(quotes):  # a mostly failed run must not replace a good file (same rule as the feed)
        raise MarketsError(f"only {good} of {len(quotes)} quotes could be read; keeping the previous file")
    return {
        "generated": now.isoformat(timespec="seconds"),
        "indexes": [quotes[s] for s in INDEXES],
        "tickers": [quotes[s] for s in extra],
    }
