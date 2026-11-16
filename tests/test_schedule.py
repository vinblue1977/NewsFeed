import json
import time
from datetime import UTC, datetime, timedelta

import pytest

from ingest.schedule import ScheduleError, build_schedule, is_due, parse_week


def event(game_id: str, week: int, date: str, home: str = "Home Team", away: str = "Away Team") -> dict:
    def side(kind: str, name: str) -> dict:
        return {"homeAway": kind, "team": {"displayName": name, "abbreviation": name[:3].upper()}}

    return {
        "id": game_id,
        "date": date,
        "week": {"number": week},
        "competitions": [{"competitors": [side("home", home), side("away", away)]}],
    }


def board(week: int, *events: dict, season_type: int = 2) -> bytes:
    return json.dumps({"week": {"number": week}, "season": {"type": season_type, "year": 2026}, "events": list(events)}).encode()


def test_parse_week_reads_games_and_skips_a_malformed_one() -> None:
    body = board(
        11,
        event("1", 11, "2026-11-19T01:15Z", "Chicago Bears", "Detroit Lions"),
        {"id": "x"},
        event("2", 11, "2026-11-22T18:00Z"),
    )
    week, season_type, games, skipped = parse_week(body)
    assert skipped == 1
    assert (week, season_type) == (11, 2)
    assert [g["id"] for g in games] == ["1", "2"]
    assert games[0]["home"] == {"name": "Chicago Bears", "abbr": "CHI"} and games[0]["away"]["name"] == "Detroit Lions"
    assert games[0]["week"] == 11 and games[0]["start"] == "2026-11-19T01:15Z"


def test_parse_week_refuses_what_is_not_a_scoreboard() -> None:
    for bad in (b"not json", b"{}", b'{"events": 5}', b'{"events": [{"id": "x"}]}'):
        with pytest.raises(ScheduleError):
            parse_week(bad)
    assert parse_week(b'{"events": []}') == (None, None, [], 0)  # an empty slate is not an error


def test_build_asks_for_each_later_week_once_and_orders_by_start() -> None:
    asked: list[str] = []

    def get(url: str) -> bytes:
        asked.append(url)
        if "week=" not in url:
            return board(16, event("a", 16, "2026-12-20T18:00Z"))
        week = int(url.split("week=")[1].split("&")[0])
        return board(
            week, event(f"g{week}", week, f"2026-12-{20 + 3 * (week - 16):02d}T18:00Z" if week == 17 else "2027-01-03T18:00Z")
        )

    got = build_schedule(getter=get)
    assert got["week"] == 16
    assert [u.split("week=")[1].split("&")[0] for u in asked if "week=" in u] == ["17", "18"]  # the current week is the base call
    assert [g["id"] for g in got["games"]] == ["a", "g17", "g18"]
    datetime.fromisoformat(got["generated"])


def test_build_survives_a_failing_week_and_outside_the_regular_season_asks_only_the_base() -> None:
    def partly(url: str) -> bytes:
        if "week=13" in url:
            raise OSError("down")
        if "week=" not in url:
            return board(12, event("a", 12, "2026-11-26T18:00Z"))
        week = int(url.split("week=")[1].split("&")[0])
        return board(week, event(f"g{week}", week, f"2026-12-{week:02d}T18:00Z"))

    built = build_schedule(getter=partly)
    ids = [g["id"] for g in built["games"]]
    assert "g13" not in ids and "g14" in ids and "a" in ids
    assert built["partial_weeks"] == [13]  # the app shows no bye for a week that may be missing a game

    asked: list[str] = []

    def playoffs(url: str) -> bytes:
        asked.append(url)
        return board(2, event("p1", 2, "2027-01-17T18:00Z"), season_type=3)

    assert [g["id"] for g in build_schedule(getter=playoffs)["games"]] == ["p1"] and len(asked) == 1


def test_build_raises_when_the_current_week_cannot_be_read() -> None:
    def down(_url: str) -> bytes:
        raise OSError("blocked")

    with pytest.raises(ScheduleError):
        build_schedule(getter=down)
    with pytest.raises(ScheduleError):
        build_schedule(getter=lambda _url: b"garbage")


def test_is_due_when_missing_old_or_unreadable() -> None:
    now = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    assert not is_due({"generated": (now - timedelta(hours=1)).isoformat()}, now)
    assert is_due({"generated": (now - timedelta(hours=7)).isoformat()}, now)
    for bad in (None, {}, {"generated": "x"}, 5):
        assert is_due(bad, now)


def test_a_skipped_game_or_a_week_that_never_answers_is_marked_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    def get(url: str) -> bytes:
        if "week=" not in url:
            return board(12, event("a", 12, "2026-11-26T18:00Z"), {"id": "broken"})  # one game cannot be read
        week = int(url.split("week=")[1].split("&")[0])
        return board(week, event(f"g{week}", week, f"2026-12-{week:02d}T18:00Z"))

    built = build_schedule(getter=get)
    assert built["partial_weeks"] == [12]
    assert [g["week"] for g in built["games"]] == [12, 13, 14, 15, 16, 17, 18]
    clean = build_schedule(getter=lambda url: board(18, event("z", 18, "2027-01-10T18:00Z")))
    assert clean["partial_weeks"] == []

    monkeypatch.setattr("ingest.schedule.WAIT_SECONDS", 0.05)

    def slow(url: str) -> bytes:
        if "week=" not in url:
            return board(16, event("a", 16, "2026-12-20T18:00Z"))
        time.sleep(0.5)
        return board(17, event("b", 17, "2026-12-27T18:00Z"))

    assert build_schedule(getter=slow)["partial_weeks"] == [17, 18]  # timed out: the weeks are flagged, not silently missing


def test_is_due_sooner_when_there_is_a_gap_and_when_the_time_is_in_the_future() -> None:
    now = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    stamp = lambda delta: (now + delta).isoformat()  # noqa: E731
    assert not is_due({"generated": stamp(-timedelta(minutes=20)), "partial_weeks": [13]}, now)
    assert is_due({"generated": stamp(-timedelta(minutes=40)), "partial_weeks": [13]}, now)  # a gap is retried after 30 minutes
    assert not is_due({"generated": stamp(-timedelta(minutes=40)), "partial_weeks": []}, now)
    assert is_due({"generated": stamp(timedelta(days=3))}, now)  # a future time is not believed
    assert not is_due({"generated": stamp(timedelta(minutes=5))}, now)  # a little clock skew is fine
