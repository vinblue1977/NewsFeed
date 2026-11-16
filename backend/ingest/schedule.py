"""The rest of the NFL regular season, for data/schedule.json (public: it is the same league schedule for everyone).

ESPN's scoreboard gives one week per request (`?week=N&seasontype=2`; a date range is refused), so the build asks for the
current week and each week after it, up to week 18. The app picks out the teams the user follows, on the device, so the
followed teams never reach the server. ESPN's API is unofficial: a week that cannot be read is skipped, and only when no
week could be read does the build raise, so the previous file stays."""

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta
from typing import Any

from ingest.feeds import clean_text, fetch

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
WEEK_URL = BASE_URL + "?week={week}&seasontype=2"
LAST_WEEK = 18  # the regular season
REGULAR_SEASON = 2
WORKERS = 6
WAIT_SECONDS = 12  # a hard cap on all the weeks together
DEADLINE_SECONDS = 6
REFRESH_HOURS = 6  # the league moves games to prime time days ahead, not minutes
RETRY_MINUTES = 30  # a schedule with a gap (a week or a game that could not be read) is tried again after this long
CLOCK_SKEW_HOURS = 1  # a `generated` time further ahead than this is not believed


class ScheduleError(Exception):
    """No week of the schedule could be read, or an answer was not usable."""


def _team(competitor: dict[str, Any]) -> dict[str, str]:
    team = competitor["team"]
    return {"name": clean_text(team["displayName"], 40), "abbr": clean_text(team.get("abbreviation"), 5)}


def parse_week(body: bytes) -> tuple[int | None, int | None, list[dict[str, Any]], int]:
    """(week number, season type, games, how many games were skipped) from one scoreboard answer. A malformed game is skipped
    and counted; an answer that is not a scoreboard raises ScheduleError."""
    try:
        data = json.loads(body)
        week = data.get("week", {}).get("number")
        season_type = data.get("season", {}).get("type")
        events = data["events"]
        games = []
        for event in events:
            try:
                teams = {c["homeAway"]: c for c in event["competitions"][0]["competitors"]}
                games.append(
                    {
                        "id": str(event["id"]),
                        "week": int(event["week"]["number"]),
                        "start": str(event["date"]),
                        "home": _team(teams["home"]),
                        "away": _team(teams["away"]),
                    }
                )
            except KeyError, IndexError, TypeError, ValueError, AttributeError:
                continue
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ScheduleError(f"not usable ({type(exc).__name__})") from exc
    if events and not games:  # games came with data but none could be read: the payload shape changed
        raise ScheduleError("games present but none could be read")
    return (
        week if isinstance(week, int) else None,
        season_type if isinstance(season_type, int) else None,
        games,
        len(events) - len(games),
    )


def build_schedule(*, getter: Callable[[str], bytes] | None = None) -> dict[str, Any]:
    """{"generated", "week", "games", "partial_weeks"}: the current week's slate and every later regular-season week, soonest
    first. `partial_weeks` lists the weeks that may be missing a game (a request failed or timed out, or a game could not be
    read): the app shows no bye for them. Outside the regular season only the current scoreboard is kept. Raises
    ScheduleError when the current week cannot be read."""
    get = getter or (lambda url: fetch(url, accept="application/json", deadline_seconds=DEADLINE_SECONDS))
    try:
        week, season_type, games, skipped = parse_week(get(BASE_URL))
    except Exception as exc:
        raise ScheduleError("the current week could not be read; keeping the previous file") from exc
    by_id = {g["id"]: g for g in games}
    partial: set[int] = {week} if skipped and week is not None else set()
    if season_type == REGULAR_SEASON and week is not None and week < LAST_WEEK:
        later = range(week + 1, LAST_WEEK + 1)
        pool = ThreadPoolExecutor(max_workers=WORKERS)
        try:
            futures = {w: pool.submit(lambda w=w: parse_week(get(WEEK_URL.format(week=w)))) for w in later}
            wait(list(futures.values()), timeout=WAIT_SECONDS)
            for w, future in futures.items():
                if future.done() and future.exception() is None:
                    _, _, found, missed = future.result()
                    by_id.update({g["id"]: g for g in found})
                    if missed:
                        partial.add(w)
                else:
                    partial.add(w)  # slow, refused or unreadable: this week may be missing from the file
        finally:
            pool.shutdown(wait=False, cancel_futures=True)  # a stalled request is abandoned, not waited for
    ordered = sorted(by_id.values(), key=lambda g: (g["start"], g["id"]))
    return {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "week": week,
        "games": ordered,
        "partial_weeks": sorted(partial),
    }


def is_due(previous: Any, now: datetime | None = None) -> bool:
    """Whether the schedule needs rebuilding: there is none, it is older than REFRESH_HOURS, one with a gap is older than
    RETRY_MINUTES, or its time is in the future (a bad clock or a hand-edited file)."""
    try:
        age = (now or datetime.now(UTC)) - datetime.fromisoformat(previous["generated"])
        if age < -timedelta(hours=CLOCK_SKEW_HOURS):
            return True
        has_gap = bool(previous.get("partial_weeks"))
        return age > (timedelta(minutes=RETRY_MINUTES) if has_gap else timedelta(hours=REFRESH_HOURS))
    except KeyError, TypeError, ValueError, AttributeError:
        return True
