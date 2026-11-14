import json
import threading
from datetime import UTC, datetime
from typing import Any

import pytest

from ingest import markets
from ingest.feeds import FeedError
from ingest.markets import INDEXES, MarketsError, build_markets, chart_url, downsample, parse_quote


@pytest.fixture(autouse=True)
def fresh_history_cache() -> None:
    markets._HISTORY.clear()


NOW = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)
TS = int(NOW.timestamp())


def chart(price: Any = 105.5, prev: Any = 100.0, closes: Any = None, **meta: Any) -> bytes:
    doc_meta: dict[str, Any] = {
        "currency": "USD",
        "symbol": "AAA",
        "shortName": "Example Corp",
        "regularMarketPrice": price,
        "regularMarketTime": TS - 60,  # traded a minute ago
        "chartPreviousClose": prev,
        "regularMarketDayHigh": 106.0,
        "regularMarketDayLow": 99.0,
        "currentTradingPeriod": {"regular": {"start": TS - 3600, "end": TS + 3600}},
        **meta,
    }
    doc_meta = {k: v for k, v in doc_meta.items() if v is not _MISSING}
    closes = [101.0, 102.5, None, 105.5] if closes is None else closes
    return json.dumps(
        {
            "chart": {
                "result": [{"meta": doc_meta, "indicators": {"quote": [{"close": closes, "open": [None, 100.5, 101.0, 102.0]}]}}],
                "error": None,
            }
        }
    ).encode()


_MISSING = object()


def test_parse_quote_computes_the_change() -> None:
    q = parse_quote("AAA", chart(), NOW)
    assert q == {
        "symbol": "AAA",
        "name": "Example Corp",
        "ok": True,
        "price": 105.5,
        "prev_close": 100.0,
        "change": 5.5,
        "change_pct": 5.5,
        "currency": "USD",
        "day_open": 100.5,  # the first open that is not a gap
        "day_high": 106.0,
        "day_low": 99.0,
        "last_trade": "2026-11-13T14:59:00+00:00",
        "open": True,
        "series": [101.0, 102.5, 105.5],  # the gap is dropped
    }


@pytest.mark.parametrize(
    "meta",
    [
        {"currentTradingPeriod": None},
        {"currentTradingPeriod": {"regular": None}},
        {"currentTradingPeriod": {}},
    ],
)
def test_explicit_nulls_in_the_trading_period_do_not_fail_a_valid_quote(meta: dict[str, Any]) -> None:
    q = parse_quote("AAA", chart(**meta), NOW)
    assert q["ok"] is True and q["price"] == 105.5 and q["open"] is False


def test_null_indicators_do_not_fail_a_valid_quote() -> None:
    doc = json.loads(chart())
    doc["chart"]["result"][0]["indicators"] = None
    q = parse_quote("AAA", json.dumps(doc).encode(), NOW)
    assert q["ok"] is True and q["series"] == []


def test_last_trade_is_an_iso_utc_time_or_none() -> None:
    assert parse_quote("AAA", chart(regularMarketTime=TS - 86400), NOW)["last_trade"] == "2026-11-12T15:00:00+00:00"
    assert parse_quote("AAA", chart(regularMarketTime=_MISSING), NOW)["last_trade"] is None
    assert parse_quote("AAA", chart(regularMarketTime=1e20), NOW)["last_trade"] is None  # out of range, not a crash
    assert parse_quote("AAA", chart(regularMarketTime=0), NOW)["last_trade"] is None  # 0 means "no trades", not 1970


def test_parse_quote_knows_when_the_market_is_closed() -> None:
    later = datetime(2026, 11, 13, 21, 0, tzinfo=UTC)
    assert parse_quote("AAA", chart(), later)["open"] is False


def test_parse_quote_without_a_trading_period_is_not_open() -> None:
    assert parse_quote("AAA", chart(currentTradingPeriod=_MISSING), NOW)["open"] is False


def test_an_exchange_holiday_is_not_open_even_inside_the_session_window() -> None:
    assert parse_quote("AAA", chart(regularMarketTime=TS - 86400), NOW)["open"] is False


@pytest.mark.parametrize("traded", [_MISSING, TS + 600, "x"])
def test_open_needs_a_sane_last_trade_time(traded: Any) -> None:
    assert parse_quote("AAA", chart(regularMarketTime=traded), NOW)["open"] is False


def test_parse_quote_falls_back_to_previous_close() -> None:
    q = parse_quote("AAA", chart(prev=None, chartPreviousClose=None, previousClose=50.0, regularMarketPrice=55.0), NOW)
    assert q["prev_close"] == 50.0 and q["change"] == 5.0 and q["change_pct"] == 10.0


def test_parse_quote_without_any_previous_close_has_no_change() -> None:
    q = parse_quote("AAA", chart(prev=None, chartPreviousClose=None), NOW)
    assert q["prev_close"] is None and q["change"] is None and q["change_pct"] is None


def test_parse_quote_name_falls_back_to_long_name_then_symbol() -> None:
    assert parse_quote("AAA", chart(shortName=None, longName="Long Name Inc"), NOW)["name"] == "Long Name Inc"
    assert parse_quote("AAA", chart(shortName=None), NOW)["name"] == "AAA"


def test_parse_quote_strips_markup_from_names() -> None:
    assert parse_quote("AAA", chart(shortName="<b>Bold</b> Co"), NOW)["name"] == "Bold Co"


def test_parse_quote_tolerates_missing_series() -> None:
    assert parse_quote("AAA", chart(closes=[]), NOW)["series"] == []
    doc = json.loads(chart())
    doc["chart"]["result"][0]["indicators"] = {}
    assert parse_quote("AAA", json.dumps(doc).encode(), NOW)["series"] == []
    doc["chart"]["result"][0]["indicators"] = {"quote": [{"close": None}]}
    assert parse_quote("AAA", json.dumps(doc).encode(), NOW)["series"] == []


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b"{}",
        json.dumps({"chart": {"result": []}}).encode(),
        json.dumps({"chart": {"result": None}}).encode(),
        json.dumps({"chart": {"result": [{"meta": {}}]}}).encode(),
        chart(price=None),
        chart(price="105"),
        chart(price=True),
        chart(price=float("nan")),
    ],
)
def test_parse_quote_rejects_bad_input(body: bytes) -> None:
    with pytest.raises(MarketsError):
        parse_quote("AAA", body, NOW)


def test_downsample_keeps_short_series_and_both_ends_of_long_ones() -> None:
    short = [1.0, 2.0, 3.0]
    assert downsample(short) == short
    long = [float(i) for i in range(100)]
    got = downsample(long)
    assert len(got) == markets.SERIES_POINTS and got[0] == 0.0 and got[-1] == 99.0
    assert got == sorted(got)


def test_chart_url_quotes_the_symbol() -> None:
    assert chart_url("^GSPC") == "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?interval=5m&range=1d"


def make_getter(bodies: dict[str, bytes | Exception]) -> Any:
    def get(url: str) -> bytes:
        symbol = url.split("/chart/")[1].split("?")[0].replace("%5E", "^")
        body = bodies.get(symbol, FeedError("fetch failed: 404"))
        if isinstance(body, Exception):
            raise body
        return body

    return get


def test_build_markets_reports_indexes_and_tickers() -> None:
    bodies = {s: chart() for s in (*INDEXES, "AAA", "BBB.NS")}
    doc = build_markets(["AAA", "BBB.NS"], getter=make_getter(bodies), now=NOW)
    assert doc["generated"] == "2026-11-13T15:00:00+00:00"
    assert [q["symbol"] for q in doc["indexes"]] == list(INDEXES)
    assert [q["symbol"] for q in doc["tickers"]] == ["AAA", "BBB.NS"]
    assert all(q["ok"] for q in [*doc["indexes"], *doc["tickers"]])


def test_one_bad_symbol_does_not_sink_the_others() -> None:
    bodies: dict[str, bytes | Exception] = {s: chart() for s in INDEXES}
    bodies["^DJI"] = FeedError("fetch failed: 500")
    bodies["BAD"] = b"garbage"
    doc = build_markets(["BAD", "MISSING"], getter=make_getter(bodies), now=NOW)
    by_symbol = {q["symbol"]: q["ok"] for q in [*doc["indexes"], *doc["tickers"]]}
    assert by_symbol["^DJI"] is False and by_symbol["BAD"] is False and by_symbol["MISSING"] is False
    assert by_symbol["^GSPC"] is True
    assert {"symbol": "BAD", "ok": False, "history": []} in doc["tickers"]


def test_tickers_are_deduplicated_and_validated() -> None:
    seen: list[str] = []

    def get(url: str) -> bytes:
        seen.append(url)
        return chart()

    doc = build_markets(["AAA", "aaa", "AAA", "^GSPC", "^gspc", "bad symbol", "x" * 40, "..", "-AAA"], getter=get, now=NOW)
    assert [q["symbol"] for q in doc["tickers"]] == ["AAA"]  # case-insensitive, no index repeats, no odd symbols
    assert len(seen) == len(INDEXES) + 2  # each index once; the one ticker twice (quote and 3-month history)


def test_no_tickers_is_fine() -> None:
    assert build_markets(getter=lambda url: chart(), now=NOW)["tickers"] == []


def test_build_markets_raises_when_nothing_could_be_read() -> None:
    with pytest.raises(MarketsError, match="previous file"):
        build_markets(["AAA"], getter=make_getter({}), now=NOW)


def test_a_mostly_failed_run_keeps_the_previous_file() -> None:
    with pytest.raises(MarketsError, match="only 1 of 5"):
        build_markets(getter=make_getter({"^GSPC": chart()}), now=NOW)
    doc = build_markets(getter=make_getter({s: chart() for s in INDEXES[:3]}), now=NOW)  # 3 of 5 is enough
    assert [q["ok"] for q in doc["indexes"]] == [True, True, True, False, False]


def test_a_stalled_request_times_out_instead_of_hanging(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()
    monkeypatch.setattr(markets, "WAIT_SECONDS", 0.05)

    def get(url: str) -> bytes:
        if not any(s in url for s in ("%5EGSPC", "%5EIXIC", "%5EDJI")):
            release.wait(5)
        return chart()

    doc = build_markets(getter=get, now=NOW)
    release.set()
    assert [q["ok"] for q in doc["indexes"]] == [True, True, True, False, False]


def test_every_symbol_gets_a_worker_so_none_waits_in_a_queue_and_times_out() -> None:
    symbols = len(INDEXES) + 2 * 20  # a quote request for every symbol and a history request for every ticker
    barrier = threading.Barrier(symbols, timeout=3)  # releases only if all 45 requests are in flight at the same time

    def together(url: str) -> bytes:
        barrier.wait()  # with fewer workers than symbols this never completes, and BrokenBarrierError fails the quote
        return chart()

    doc = build_markets([f"T{i}" for i in range(20)], getter=together, now=NOW)
    assert all(q["ok"] for q in [*doc["indexes"], *doc["tickers"]]) and len(doc["tickers"]) == 20


def test_default_getter_uses_json_accept_and_short_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_fetch(url: str, **kw: Any) -> bytes:
        calls.append((url, kw))
        return chart()

    monkeypatch.setattr(markets, "fetch", fake_fetch)
    build_markets(now=NOW)
    assert len(calls) == len(INDEXES)
    expected = {"accept": markets.JSON_ACCEPT, "deadline_seconds": markets.DEADLINE_SECONDS, "user_agent": markets.USER_AGENT}
    assert all(kw == expected for _, kw in calls)


def history_chart(closes: list[Any]) -> bytes:
    return json.dumps({"chart": {"result": [{"meta": {}, "indicators": {"quote": [{"close": closes}]}}]}}).encode()


def test_parse_history_keeps_the_finite_daily_closes() -> None:
    assert markets.parse_history(history_chart([1.0, None, 2.5, "x", 3.0])) == [1.0, 2.5, 3.0]
    assert len(markets.parse_history(history_chart([float(i) for i in range(200)]))) == markets.HISTORY_POINTS
    for bad in (b"not json", b"{}", b'{"chart": {"result": []}}'):
        assert markets.parse_history(bad) == []


def test_watchlist_quotes_carry_a_three_month_history_and_indexes_do_not() -> None:
    def get(url: str) -> bytes:
        return history_chart([10.0, 11.0, 12.0]) if "range=3mo" in url else chart()

    doc = build_markets(["AAA"], getter=get, now=NOW)
    assert doc["tickers"][0]["history"] == [10.0, 11.0, 12.0] and doc["tickers"][0]["ok"]
    assert all("history" not in q for q in doc["indexes"])


def test_a_failed_history_request_leaves_the_quote_without_a_graph() -> None:
    def get(url: str) -> bytes:
        if "range=3mo" in url:
            raise FeedError("fetch failed: 500")
        return chart()

    doc = build_markets(["AAA"], getter=get, now=NOW)
    assert doc["tickers"][0]["ok"] and doc["tickers"][0]["history"] == []


def test_history_is_fetched_once_then_reused_until_it_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []

    def get(url: str) -> bytes:
        urls.append(url)
        return history_chart([1.0, 2.0]) if "range=3mo" in url else chart()

    clock = [1000.0]
    monkeypatch.setattr(markets.time, "monotonic", lambda: clock[0])
    build_markets(["AAA"], getter=get, now=NOW)
    build_markets(["AAA"], getter=get, now=NOW)
    assert sum("range=3mo" in u for u in urls) == 1  # the second refresh reused it
    clock[0] += markets.HISTORY_TTL_SECONDS + 1
    build_markets(["AAA"], getter=get, now=NOW)
    assert sum("range=3mo" in u for u in urls) == 2


def test_an_old_graph_is_kept_when_the_refetch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(markets.time, "monotonic", lambda: clock[0])
    ok = lambda url: history_chart([1.0, 2.0]) if "range=3mo" in url else chart()  # noqa: E731
    build_markets(["AAA"], getter=ok, now=NOW)
    clock[0] += markets.HISTORY_TTL_SECONDS + 1

    def down(url: str) -> bytes:
        if "range=3mo" in url:
            raise FeedError("fetch failed: 429")
        return chart()

    assert build_markets(["AAA"], getter=down, now=NOW)["tickers"][0]["history"] == [1.0, 2.0]
