"""The pre-market read for the Markets screen: which way US stocks are leaning before the open.

Index futures (S&P, Nasdaq, Dow) set the direction; the VIX and the 10-year Treasury yield confirm or soften it. It is a
signal, not a forecast, so the labels say "leaning". Only built on a US trading day between 4:00 and 9:30 AM Eastern: weekends
and NYSE holidays (computed from the rules, so there is no list to keep up to date) get nothing, and the app then shows no
banner. An unscheduled closure (a national day of mourning, say) is not known in advance and is not modelled."""

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
FUTURES = (("ES=F", "S&P"), ("NQ=F", "Nasdaq"), ("YM=F", "Dow"))
VIX = "^VIX"
TEN_YEAR = "^TNX"  # quoted in percent (4.95 means 4.95%)
SYMBOLS = (*(s for s, _ in FUTURES), VIX, TEN_YEAR)

OPENS_MINUTE = 4 * 60  # pre-market trading starts at 4:00 AM Eastern
CLOSES_MINUTE = 9 * 60 + 30  # the regular session starts at 9:30
FUTURES_FRESH_SECONDS = 30 * 60  # futures trade almost around the clock: an older last trade means the data is stale
INDEX_FRESH_SECONDS = 90 * 60  # the VIX and the yield index update less often before the open
LEAN_PCT = 0.25  # the futures' average move that counts as a lean
VIX_PCT = 3.0  # a VIX move this big (percent) is a vote
YIELD_BP = 3.0  # a yield move this big (basis points) is a vote


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _easter(year: int) -> date:
    """Western Easter (the anonymous Gregorian algorithm); Good Friday is two days before."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month, day = divmod(h + el - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _observed(day: date) -> date:
    """A fixed-date holiday that falls on a weekend is observed on the Friday before or the Monday after."""
    return day - timedelta(days=1) if day.weekday() == 5 else day + timedelta(days=1) if day.weekday() == 6 else day


def market_holidays(year: int) -> set[date]:
    """The NYSE full-day closures of one year (an early close, such as the day after Thanksgiving, is still a trading day)."""
    holidays = {
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Presidents Day
        _easter(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed(date(year, 6, 19)),  # Juneteenth
        _observed(date(year, 7, 4)),  # Independence Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed(date(year, 12, 25)),  # Christmas
    }
    if date(year, 1, 1).weekday() != 5:  # a New Year's Day on a Saturday is not observed on the Friday
        holidays.add(_observed(date(year, 1, 1)))
    return holidays


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in market_holidays(day.year)


def in_window(now: datetime) -> bool:
    """A US trading day, 4:00 AM up to 9:30 AM Eastern."""
    local = now.astimezone(NEW_YORK)
    return is_trading_day(local.date()) and OPENS_MINUTE <= local.hour * 60 + local.minute < CLOSES_MINUTE


def _age(quote: dict[str, Any], now: datetime) -> float | None:
    """Seconds since the last trade, or None if it is not known."""
    try:
        return (now - datetime.fromisoformat(str(quote["last_trade"]))).total_seconds()
    except KeyError, ValueError, TypeError:
        return None


def _usable(quote: dict[str, Any] | None, now: datetime, fresh_seconds: int) -> bool:
    if not quote or quote.get("ok") is not True or quote.get("price") is None:
        return False
    age = _age(quote, now)
    return (
        age is not None and -300 <= age <= fresh_seconds
    )  # a last trade from the future (clock skew) beyond 5 minutes is not believed


def _vote(value: float | None, threshold: float, *, falling_is_good: bool) -> int:
    """+1 when the move supports stocks, -1 when it weighs on them, 0 when it is too small or unknown."""
    if value is None or abs(value) < threshold:
        return 0
    return (1 if value < 0 else -1) if falling_is_good else (1 if value > 0 else -1)


def read(quotes: dict[str, dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    """The pre-market read from quotes keyed by symbol, or None outside the window or without enough futures.

    state: "bull" or "bear" when the VIX and the yield back the futures' direction and neither argues against it,
    "lean_up" or "lean_down" when the futures lean but the others are silent or disagree, "flat" when the futures are
    quiet (the VIX and the yield are shown but do not decide)."""
    if not in_window(now):
        return None
    futures = [
        {"symbol": s, "name": name, "change_pct": quotes[s]["change_pct"]}
        for s, name in FUTURES
        if _usable(quotes.get(s), now, FUTURES_FRESH_SECONDS) and quotes[s].get("change_pct") is not None
    ]
    if len(futures) < 2:  # one future alone is too thin to call a direction
        return None
    average = sum(f["change_pct"] for f in futures) / len(futures)
    vix, ten = quotes.get(VIX), quotes.get(TEN_YEAR)
    vix_out: dict[str, Any] | None = None
    if vix and _usable(vix, now, INDEX_FRESH_SECONDS) and vix.get("change_pct") is not None:
        vix_out = {
            "price": vix["price"],
            "change_pct": vix["change_pct"],
            "vote": _vote(vix["change_pct"], VIX_PCT, falling_is_good=True),
        }
    ten_out: dict[str, Any] | None = None
    if ten and _usable(ten, now, INDEX_FRESH_SECONDS) and ten.get("prev_close") is not None:
        bp = round((ten["price"] - ten["prev_close"]) * 100)
        ten_out = {"price": ten["price"], "change_bp": bp, "vote": _vote(bp, YIELD_BP, falling_is_good=True)}
    votes = [x["vote"] for x in (vix_out, ten_out) if x]
    if abs(average) < LEAN_PCT:
        state = "flat"
    else:
        sign = 1 if average > 0 else -1
        agrees, opposes = any(v * sign > 0 for v in votes), any(v * sign < 0 for v in votes)
        strong = agrees and not opposes
        state = ("bull" if strong else "lean_up") if sign > 0 else ("bear" if strong else "lean_down")
    return {"state": state, "futures": futures, "vix": vix_out, "yield10": ten_out}
