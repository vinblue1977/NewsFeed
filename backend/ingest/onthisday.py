"""The "on this day" facts for data/onthisday.json, from Wikipedia's featured events (free, keyless).

The file holds one event for each of three days around the current UTC day, so a reader's own calendar day (anywhere from
UTC-12 to UTC+14) is always in it. It is rebuilt once a day: each day's event is picked by its date alone."""

import html
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from ingest.feeds import fetch

ONTHISDAY_URL = "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/selected/{month:02d}/{day:02d}"
USER_AGENT = "NewsPWA/1.0 (personal news reader)"  # Wikimedia asks API clients to identify themselves
DEADLINE_SECONDS = 6
MAX_CHARS = 160
_TAGS = re.compile(r"<[^>]*>")
_PICTURED = re.compile(r"\s*\([^()]*pictured[^()]*\)", re.IGNORECASE)  # "(the defendants pictured)": there is no picture here


class OnThisDayError(Exception):
    """Wikipedia's list could not be read or held no usable event."""


def clean(text: str) -> str:
    """Plain one-line text: no markup, entities decoded, picture captions and extra spaces gone."""
    return re.sub(r"\s+", " ", _PICTURED.sub("", html.unescape(_TAGS.sub("", text)))).strip()


def parse_events(raw: bytes) -> list[dict[str, Any]]:
    """The usable events as {"year", "text"}: a year of 1 to 4 digits and a non-empty text, nothing else kept."""
    try:
        events = json.loads(raw)["selected"]
    except (ValueError, KeyError, TypeError) as exc:
        raise OnThisDayError("not an on-this-day list") from exc
    if not isinstance(events, list):
        raise OnThisDayError("not an on-this-day list")
    out: list[dict[str, Any]] = []
    for e in events:
        year, text = (e.get("year"), e.get("text")) if isinstance(e, dict) else (None, None)
        if isinstance(year, bool) or not isinstance(year, int) or not 1 <= year <= 9999 or not isinstance(text, str):
            continue
        text = clean(text)
        if text:
            out.append({"year": year, "text": text})
    return out


def shorten(text: str) -> str:
    """`text` cut at a word end (or hard, if there is none) with an ellipsis when it is longer than MAX_CHARS."""
    if len(text) <= MAX_CHARS:
        return text
    cut = text[: MAX_CHARS - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(",;:- ") + "…"


def pick(events: list[dict[str, Any]], day: datetime) -> dict[str, Any]:
    """The day's event: chosen by the date, from those short enough to show whole when there are any."""
    if not events:
        raise OnThisDayError("no usable event for today")
    short = [e for e in events if len(e["text"]) <= MAX_CHARS]
    pool = short or events
    chosen = pool[day.date().toordinal() % len(pool)]
    return {"year": chosen["year"], "text": shorten(chosen["text"])}


def is_due(previous: Any, now: datetime | None = None) -> bool:
    """Whether to rebuild: there is no readable file, or it was built for another UTC day."""
    try:
        return previous["date"] != (now or datetime.now(UTC)).date().isoformat()
    except KeyError, TypeError:
        return True


def build_onthisday(*, getter: Any = None, now: datetime | None = None) -> dict[str, Any]:
    """{"generated", "date": the UTC day built on, "days": {yyyy-mm-dd: {"year", "text"}}} for the day before, the day and the
    day after. Raises if the day itself cannot be read, so the previous file stays; a neighbour that cannot is left out."""
    now = now or datetime.now(UTC)
    get = getter or (lambda u: fetch(u, accept="application/json", deadline_seconds=DEADLINE_SECONDS, user_agent=USER_AGENT))
    days: dict[str, dict[str, Any]] = {}
    for offset in (0, -1, 1):  # the day itself first: it must work
        day = now + timedelta(days=offset)
        try:
            days[day.date().isoformat()] = pick(parse_events(get(ONTHISDAY_URL.format(month=day.month, day=day.day))), day)
        except Exception:  # noqa: BLE001  (a neighbouring day that cannot be read is left out)
            if offset == 0:
                raise
    return {"generated": now.isoformat(timespec="seconds"), "date": now.date().isoformat(), "days": dict(sorted(days.items()))}
