from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from ingest.premarket import FUTURES, TEN_YEAR, VIX, in_window, is_trading_day, market_holidays, read

NOW = datetime(2026, 11, 20, 13, 0, tzinfo=UTC)  # Friday, 8:00 AM EST


def quote(
    price: float = 100.0, pct: float | None = 0.0, prev: float | None = None, ago: int = 60, ok: bool = True
) -> dict[str, Any]:
    return {
        "ok": ok,
        "price": price,
        "change_pct": pct,
        "prev_close": prev,
        "last_trade": (NOW - timedelta(seconds=ago)).isoformat(),
    }


def quotes(
    es: float = 0.5, nq: float = 0.7, ym: float = 0.3, vix: float | None = None, bp: float | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {s: quote(pct=p) for (s, _), p in zip(FUTURES, (es, nq, ym), strict=True)}
    if vix is not None:
        out[VIX] = quote(20.0, vix)
    if bp is not None:
        out[TEN_YEAR] = quote(4.0 + bp / 100, prev=4.0)
    return out


def test_the_nyse_holidays_of_2026_and_2027() -> None:
    assert sorted(market_holidays(2026)) == [
        date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25),
        date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
    ]  # fmt: skip
    assert sorted(market_holidays(2027)) == [
        date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26), date(2027, 5, 31),
        date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6), date(2027, 11, 25), date(2027, 12, 24),
    ]  # fmt: skip


def test_new_years_day_on_a_saturday_is_not_observed_on_the_friday() -> None:
    assert date(2022, 1, 1).weekday() == 5
    assert is_trading_day(date(2021, 12, 31)) and not is_trading_day(date(2022, 1, 1))


def test_weekends_and_holidays_are_not_trading_days() -> None:
    assert is_trading_day(date(2026, 11, 20)) and is_trading_day(
        date(2026, 11, 27)
    )  # the day after Thanksgiving is a short day, still open
    assert not is_trading_day(date(2026, 11, 21)) and not is_trading_day(date(2026, 11, 26))


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (datetime(2026, 11, 20, 8, 59, tzinfo=UTC), False),  # 3:59 AM EST
        (datetime(2026, 11, 20, 9, 0, tzinfo=UTC), True),  # 4:00 AM EST
        (datetime(2026, 11, 20, 14, 29, tzinfo=UTC), True),  # 9:29 AM EST
        (datetime(2026, 11, 20, 14, 30, tzinfo=UTC), False),  # 9:30 AM EST: the open
        (datetime(2026, 7, 10, 7, 59, tzinfo=UTC), False),  # 3:59 AM EDT (summer time)
        (datetime(2026, 7, 10, 8, 0, tzinfo=UTC), True),  # 4:00 AM EDT
        (datetime(2026, 7, 10, 13, 30, tzinfo=UTC), False),  # 9:30 AM EDT
        (datetime(2026, 11, 21, 13, 0, tzinfo=UTC), False),  # Saturday
        (datetime(2026, 11, 26, 13, 0, tzinfo=UTC), False),  # Thanksgiving
    ],
)
def test_the_window_is_4_to_930_eastern_on_trading_days(when: datetime, expected: bool) -> None:
    assert in_window(when) is expected


def test_outside_the_window_there_is_no_read() -> None:
    assert read(quotes(), datetime(2026, 11, 26, 13, 0, tzinfo=UTC)) is None


@pytest.mark.parametrize(
    ("kwargs", "state"),
    [
        ({"vix": -4.0, "bp": -3}, "bull"),  # all agree
        ({"vix": -4.0}, "bull"),  # one confirms, the other is missing
        ({}, "lean_up"),  # futures alone
        ({"vix": 8.0, "bp": 5}, "lean_up"),  # both argue against
        ({"vix": -4.0, "bp": 5}, "lean_up"),  # one for, one against
        ({"vix": 1.0, "bp": 1}, "lean_up"),  # too small to vote
        ({"es": 0.1, "nq": 0.2, "ym": 0.0, "vix": 9.0}, "flat"),  # quiet futures: the others do not decide
    ],
)
def test_futures_set_the_direction_and_the_others_confirm_or_soften_it(kwargs: dict[str, float], state: str) -> None:
    assert (read(quotes(**kwargs), NOW) or {})["state"] == state


@pytest.mark.parametrize(
    ("kwargs", "state"),
    [
        ({"vix": 11.0, "bp": 9}, "bear"),
        ({"vix": 11.0}, "bear"),
        ({}, "lean_down"),
        ({"vix": -5.0, "bp": -4}, "lean_down"),
    ],
)
def test_the_bearish_mirror(kwargs: dict[str, float], state: str) -> None:
    assert (read(quotes(es=-0.8, nq=-1.3, ym=-0.5, **kwargs), NOW) or {})["state"] == state


def test_the_read_carries_the_numbers_the_screen_shows() -> None:
    doc = read(quotes(vix=-3.1, bp=-2), NOW)
    assert doc is not None
    assert doc["futures"] == [
        {"symbol": "ES=F", "name": "S&P", "change_pct": 0.5},
        {"symbol": "NQ=F", "name": "Nasdaq", "change_pct": 0.7},
        {"symbol": "YM=F", "name": "Dow", "change_pct": 0.3},
    ]
    assert doc["vix"] == {"price": 20.0, "change_pct": -3.1, "vote": 1}
    assert doc["yield10"] == {"price": 3.98, "change_bp": -2, "vote": 0}  # 2 bp is under the 3 bp threshold


def test_a_read_needs_two_fresh_futures() -> None:
    one = quotes()
    del one["NQ=F"]
    del one["YM=F"]
    assert read(one, NOW) is None
    stale = quotes()
    stale["NQ=F"] = quote(pct=0.7, ago=31 * 60)
    stale["YM=F"] = quote(pct=0.3, ok=False)
    assert read(stale, NOW) is None  # one fresh future is not enough
    stale["NQ=F"] = quote(pct=0.7)
    assert read(stale, NOW)["futures"][1]["symbol"] == "NQ=F"  # type: ignore[index]  # ES and NQ are enough


def test_a_stale_vix_or_yield_is_left_out_not_counted() -> None:
    q = quotes()
    q[VIX] = quote(20.0, -9.0, ago=2 * 3600)
    q[TEN_YEAR] = quote(4.0, prev=None)
    doc = read(q, NOW)
    assert doc is not None and doc["vix"] is None and doc["yield10"] is None and doc["state"] == "lean_up"


def test_a_quote_without_a_trade_time_is_not_used() -> None:
    q = quotes()
    for s, _ in FUTURES:
        q[s]["last_trade"] = None
    assert read(q, NOW) is None
