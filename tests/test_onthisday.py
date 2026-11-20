import json
from datetime import UTC, datetime

import pytest

from ingest.onthisday import MAX_CHARS, ONTHISDAY_URL, OnThisDayError, build_onthisday, clean, is_due, parse_events, pick, shorten

NOW = datetime(2026, 11, 20, 9, 30, tzinfo=UTC)


def listing(*events: object) -> bytes:
    return json.dumps({"selected": list(events)}).encode()


def event(year: object, text: object) -> dict[str, object]:
    return {"year": year, "text": text, "pages": []}


def test_clean_gives_plain_one_line_text() -> None:
    assert clean("Windows <b>1.0</b>,  the first &amp; best\n version") == "Windows 1.0, the first & best version"
    assert clean("The Nuremberg trials (defendants pictured) began.") == "The Nuremberg trials began."
    assert clean("Kept (a note) here") == "Kept (a note) here"


def test_parse_events_keeps_only_events_with_a_sane_year_and_text() -> None:
    raw = listing(
        event(1985, "Windows 1.0 was released."),
        event(0, "Year zero"),
        event(10000, "Too far away"),
        event(-44, "Before our era"),
        event(True, "A bool is not a year"),
        event("1990", "A string is not a year"),
        event(1990, 5),
        event(1990, "<p> </p>"),
        "not an event",
        None,
    )
    assert parse_events(raw) == [{"year": 1985, "text": "Windows 1.0 was released."}]


@pytest.mark.parametrize("raw", [b"not json", b"[]", b"{}", b'{"selected": "x"}', b'{"selected": null}'])
def test_parse_events_rejects_anything_that_is_not_a_list(raw: bytes) -> None:
    with pytest.raises(OnThisDayError):
        parse_events(raw)


def test_shorten_cuts_at_a_word_or_hard_and_leaves_short_text_alone() -> None:
    assert shorten("Short.") == "Short."
    for long in (" ".join(["word"] * 60), "x" * 500):  # the second has no space to cut at
        cut = shorten(long)
        assert len(cut) <= MAX_CHARS and cut.endswith("…") and not cut.endswith(" …")


def test_pick_is_stable_for_a_day_and_prefers_events_that_fit() -> None:
    events = [{"year": 1000 + i, "text": f"Event {i}."} for i in range(7)] + [{"year": 1, "text": "x" * 300}]
    first = pick(events, NOW)
    assert pick(events, NOW.replace(hour=23)) == first  # the same day, any run
    assert pick(events, NOW.replace(day=21)) != first  # the next day, another event
    assert all(len(pick(events, NOW.replace(day=d))["text"]) <= MAX_CHARS for d in range(1, 29))
    assert pick([{"year": 5, "text": "y" * 300}], NOW)["text"].endswith("…")  # nothing fits: the one there is is shortened
    with pytest.raises(OnThisDayError):
        pick([], NOW)


def test_is_due_when_there_is_no_readable_file_or_it_is_from_another_utc_day() -> None:
    assert not is_due({"date": "2026-11-20"}, NOW)
    for previous in (None, {}, {"date": "2026-11-19"}, {"date": "2026-11-21"}, "x", [], {"date": None}):
        assert is_due(previous, NOW)


def test_build_onthisday_holds_the_day_before_the_day_and_the_day_after() -> None:
    asked: list[str] = []

    def getter(url: str) -> bytes:
        asked.append(url)
        return listing(event(1985, "Windows 1.0 was released."), event(1947, "A royal wedding."))

    doc = build_onthisday(getter=getter, now=NOW)
    assert asked == [ONTHISDAY_URL.format(month=11, day=d) for d in (20, 19, 21)]
    assert (doc["generated"], doc["date"]) == ("2026-11-20T09:30:00+00:00", "2026-11-20")
    assert list(doc["days"]) == ["2026-11-19", "2026-11-20", "2026-11-21"]  # in date order
    assert all(set(v) == {"year", "text"} for v in doc["days"].values())


def test_build_onthisday_crosses_a_month_and_year_end() -> None:
    asked: list[str] = []

    def getter(url: str) -> bytes:
        asked.append(url.rsplit("/", 2)[1] + "/" + url.rsplit("/", 1)[1])
        return listing(event(1999, "Something happened."))

    doc = build_onthisday(getter=getter, now=datetime(2026, 12, 31, 23, 59, tzinfo=UTC))
    assert asked == ["12/31", "12/30", "01/01"] and list(doc["days"]) == ["2026-12-30", "2026-12-31", "2027-01-01"]


def test_a_neighbouring_day_that_cannot_be_read_is_left_out_but_the_day_itself_must_work() -> None:
    def no_neighbours(url: str) -> bytes:
        if url.endswith("/11/20"):
            return listing(event(1985, "Windows 1.0 was released."))
        raise OSError("offline")

    assert list(build_onthisday(getter=no_neighbours, now=NOW)["days"]) == ["2026-11-20"]

    def only_neighbours(url: str) -> bytes:
        if url.endswith("/11/20"):
            raise OSError("offline")
        return listing(event(1985, "Windows 1.0 was released."))

    with pytest.raises(OSError):
        build_onthisday(getter=only_neighbours, now=NOW)
    with pytest.raises(OnThisDayError):
        build_onthisday(getter=lambda url: listing(event(0, "no")), now=NOW)
