import json
from datetime import UTC, date, datetime, timedelta

import pytest

from ingest.earnings import EarningsError, askable, build_earnings, finnhub_symbol, is_due, parse_symbol

TODAY = date(2026, 11, 16)


def row(day: str, hour: str = "bmo", eps: object = 0.64) -> dict:
    return {"date": day, "epsEstimate": eps, "hour": hour, "quarter": 3, "symbol": "WMT", "year": 2026}


def doc(*rows: dict) -> bytes:
    return json.dumps({"earningsCalendar": list(rows)}).encode()


def test_parse_symbol_takes_the_next_report_from_today_on() -> None:
    got = parse_symbol(doc(row("2026-11-10"), row("2026-11-24", "amc", 0.85), row("2026-11-19", "bmo", 0.64)), "WMT", TODAY)
    assert got == {"symbol": "WMT", "date": "2026-11-19", "time": "pre", "eps": 0.64}
    assert parse_symbol(doc(row("2026-11-16", "amc")), "WMT", TODAY) == {
        "symbol": "WMT",
        "date": "2026-11-16",
        "time": "post",
        "eps": 0.64,
    }  # today counts


def test_parse_symbol_maps_times_and_estimates() -> None:
    assert parse_symbol(doc(row("2026-11-19", "dmh", None)), "WMT", TODAY) == {
        "symbol": "WMT",
        "date": "2026-11-19",
        "time": "tbd",
        "eps": None,
    }
    assert parse_symbol(doc(row("2026-11-19", "", "n/a")), "WMT", TODAY)["eps"] is None  # type: ignore[index]
    assert parse_symbol(doc(row("2026-11-19", "bmo", True)), "WMT", TODAY)["eps"] is None  # type: ignore[index]
    assert parse_symbol(doc(row("2026-11-19", "bmo", 2)), "WMT", TODAY)["eps"] == 2.0  # type: ignore[index]


def test_parse_symbol_has_nothing_without_a_report_and_refuses_a_wrong_shape() -> None:
    assert parse_symbol(doc(), "WMT", TODAY) is None
    assert parse_symbol(b'{"earningsCalendar": null}', "WMT", TODAY) is None
    assert parse_symbol(doc(row("2026-11-01")), "WMT", TODAY) is None  # only past reports
    for bad in (b"not json", b"{}", b'{"earningsCalendar": 5}', doc({"nodate": 1}), doc(row("not a date"))):
        with pytest.raises(EarningsError):
            parse_symbol(bad, "WMT", TODAY)


def test_which_symbols_are_asked_about_and_how_they_are_written() -> None:
    assert [askable(s) for s in ("WMT", "BRK-B", "^GSPC", "CL=F", "EURUSD=X", "")] == [True, True, False, False, False, False]
    assert finnhub_symbol("brk-b") == "BRK.B"
    assert finnhub_symbol("WMT") == "WMT"


def test_build_earnings_asks_once_per_askable_symbol_with_the_token_kept_out_of_the_url() -> None:
    urls: list[str] = []

    def get(url: str) -> bytes:
        urls.append(url)
        symbol = url.split("symbol=")[1]
        return {"WMT": doc(row("2026-11-19")), "INTU": doc(row("2026-11-19", "amc", 2.47)), "BRK.B": doc(row("2026-12-20"))}.get(
            symbol, doc()
        )

    got = build_earnings(["WMT", "INTU", "AAPL", "BRK-B", "^GSPC", "WMT"], "secret-token", today=TODAY, getter=get)
    assert [(i["symbol"], i["date"], i["time"]) for i in got["items"]] == [
        ("INTU", "2026-11-19", "post"),
        ("WMT", "2026-11-19", "pre"),
        ("BRK-B", "2026-12-20", "pre"),
    ]
    assert len(urls) == 4 and not any("secret-token" in u for u in urls)  # WMT once, no index; the token is only ever a header
    assert all("from=2026-11-16&to=2027-01-15" in u for u in urls)
    assert got["symbols"] == sorted(["WMT", "INTU", "AAPL", "BRK-B", "^GSPC", "WMT"])
    datetime.fromisoformat(got["generated"])


def test_build_earnings_survives_a_failing_symbol_but_not_a_failing_service() -> None:
    def partly(url: str) -> bytes:
        if url.endswith("symbol=AAPL"):
            raise OSError("down")
        return doc(row("2026-11-19"))

    got = build_earnings(["WMT", "AAPL"], "t", today=TODAY, getter=partly)
    assert [i["symbol"] for i in got["items"]] == ["WMT"]
    assert got["symbols"] == ["WMT"]  # AAPL failed: not claimed as covered, so the next run asks again

    def down(_url: str) -> bytes:
        raise OSError("blocked")

    with pytest.raises(EarningsError):
        build_earnings(["WMT"], "t", today=TODAY, getter=down)
    assert build_earnings(["^GSPC"], "t", today=TODAY, getter=down)["items"] == []  # nothing to ask: nothing failed


def test_is_due_when_missing_old_or_for_other_symbols() -> None:
    now = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    fresh = {"generated": (now - timedelta(hours=1)).isoformat(), "symbols": ["WMT", "AAPL"]}
    assert not is_due(fresh, ["AAPL", "WMT"], now)
    assert is_due(fresh, ["WMT"], now)  # the watchlist changed
    assert is_due({**fresh, "generated": (now - timedelta(hours=7)).isoformat()}, ["AAPL", "WMT"], now)
    for bad in (None, {}, {"generated": "x", "symbols": []}, {"generated": fresh["generated"]}):
        assert is_due(bad, ["WMT"], now)
