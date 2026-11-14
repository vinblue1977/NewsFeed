"""Sports scores for data/scores.json: NFL and ATP tennis from ESPN's scoreboard API, cricket from ESPNcricinfo's live RSS.

ESPN's API is unofficial, so each sport fails soft: `ok` says whether it could be read, and one broken sport never hides the
others. Only when fewer than half could be read does the build raise, so the previous file stays in place."""

import json
import xml.etree.ElementTree as ET  # noqa: S405  (DOCTYPE/ENTITY declarations are rejected first; see check_safe_xml)
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from ingest.feeds import FeedError, check_safe_xml, clean_text, fetch

ESPN = "https://site.api.espn.com/apis/site/v2/sports"
NFL_URL = f"{ESPN}/football/nfl/scoreboard"
ATP_URL = f"{ESPN}/tennis/atp/scoreboard"
CRICKET_URL = "https://static.espncricinfo.com/rss/livescores.xml"
JSON_ACCEPT = "application/json"
XML_ACCEPT = "application/rss+xml, application/xml, text/xml"
MAX_PER_SPORT = 20
WAIT_SECONDS = 8  # a hard cap on the whole fetch; the socket timeout alone can run longer than the fetch deadline
DEADLINE_SECONDS = 6


class ScoresError(Exception):
    """A sport's answer was not usable, or (from build_scores) no sport could be read at all."""


def _link(url: Any) -> str | None:
    """Only http(s) links with a host are kept."""
    if not isinstance(url, str):
        return None
    parts = urlsplit(url.strip())
    return url.strip() if parts.scheme in ("http", "https") and parts.netloc else None


def _state(status: Any) -> tuple[str, str]:
    """(state, detail): state is 'pre', 'live' or 'final'."""
    kind = status["type"]
    state = {"pre": "pre", "in": "live", "post": "final"}.get(kind.get("state"), "pre")
    return state, clean_text(kind.get("shortDetail") or kind.get("description"), 40)


def _event_link(links: Any) -> str | None:
    for link in links if isinstance(links, list) else []:
        if isinstance(link, dict) and "summary" in (link.get("rel") or []):
            return _link(link.get("href"))
    return None


def _score(competitor: dict[str, Any]) -> int | None:
    try:
        return int(competitor["score"])
    except KeyError, TypeError, ValueError:
        return None


def _when(start: str) -> datetime:
    """A start time as a UTC datetime, so 'Z', '+00:00' and with/without seconds all sort alike. Unparseable sorts first."""
    try:
        parsed = datetime.fromisoformat(start.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _order(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Live first, then upcoming (soonest first), then finished (latest first)."""
    rank = {"live": 0, "pre": 1, "final": 2}
    upcoming = sorted((e for e in entries if e["state"] == "pre"), key=lambda e: _when(e["start"]))
    others = sorted((e for e in entries if e["state"] != "pre"), key=lambda e: _when(e["start"]), reverse=True)
    return sorted([*upcoming, *others], key=lambda e: rank[e["state"]])


def parse_nfl(body: bytes) -> list[dict[str, Any]]:
    """ESPN NFL scoreboard JSON -> games, live first, then upcoming, then finished."""
    try:
        events = json.loads(body)["events"]
        games = []
        for event in events:
            try:  # one malformed game is skipped; the others are still shown
                teams = {c["homeAway"]: c for c in event["competitions"][0]["competitors"]}
                state, detail = _state(event["status"])
                games.append(
                    {
                        "id": str(event["id"]),
                        "state": state,
                        "detail": detail,
                        "start": str(event["date"]),
                        "home": {"name": clean_text(teams["home"]["team"]["displayName"], 40), "score": _score(teams["home"])},
                        "away": {"name": clean_text(teams["away"]["team"]["displayName"], 40), "score": _score(teams["away"])},
                        "url": _event_link(event.get("links")),
                    }
                )
            except KeyError, IndexError, TypeError, AttributeError:
                continue
    except (ValueError, KeyError, TypeError) as exc:
        raise ScoresError(f"nfl: not usable ({type(exc).__name__})") from exc
    return _order(games)[:MAX_PER_SPORT]


def parse_tennis(body: bytes) -> list[dict[str, Any]]:
    """ESPN ATP scoreboard JSON -> matches from every tournament in the feed, same ordering as NFL."""
    try:
        events = json.loads(body)["events"]
        matches = []
        for event in events:
            for group in event.get("groupings") or []:
                for comp in group.get("competitions") or []:
                    try:  # one malformed match is skipped; the others are still shown
                        state, detail = _state(comp["status"])
                        players = sorted(comp["competitors"], key=lambda c: c.get("order", 0))
                        matches.append(
                            {
                                "id": str(comp["id"]),
                                "state": state,
                                "detail": detail,
                                "start": str(comp.get("startDate") or comp["date"]),
                                "tournament": clean_text(event.get("name"), 60),
                                "players": [
                                    {
                                        "name": clean_text(p["athlete"]["displayName"], 40),
                                        "sets": [int(s["value"]) for s in p.get("linescores") or []],
                                        "winner": bool(p.get("winner")),
                                    }
                                    for p in players
                                ],
                            }
                        )
                    except KeyError, IndexError, TypeError, AttributeError, ValueError:
                        continue
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ScoresError(f"tennis: not usable ({type(exc).__name__})") from exc
    return _order(matches)[:MAX_PER_SPORT]


def parse_cricket(body: bytes) -> list[dict[str, Any]]:
    """ESPNcricinfo live-scores RSS -> matches. The title is one score line; a '*' marks the side now batting."""
    try:
        check_safe_xml(body)
        root = ET.fromstring(body)  # noqa: S314
    except (FeedError, ET.ParseError) as exc:
        raise ScoresError(f"cricket: not usable ({type(exc).__name__})") from exc
    matches = []
    for item in root.iter("item"):
        line = clean_text(item.findtext("title"))
        if line:
            ident = clean_text(item.findtext("guid") or item.findtext("link"), 200)  # stable; the score line changes every update
            matches.append(
                {
                    "id": ident if _link(ident) else line,
                    "line": line,
                    "live": "*" in line,
                    "url": _link(item.findtext("link")),
                }
            )
    return matches[:MAX_PER_SPORT]


def _read(url: str, accept: str, parse: Any, get: Any) -> dict[str, Any]:
    try:
        return {"ok": True, "entries": parse(get(url, accept))}
    except FeedError, ScoresError:
        return {"ok": False, "entries": []}


def build_scores(*, getter: Any = None, now: datetime | None = None) -> dict[str, Any]:
    """{"generated", "nfl": {"ok", "entries"}, "tennis": {...}, "cricket": {...}}. Raises ScoresError if under half are read."""
    now = now or datetime.now(UTC)
    get = getter or (lambda url, accept: fetch(url, accept=accept, deadline_seconds=DEADLINE_SECONDS))
    jobs = {
        "nfl": (NFL_URL, JSON_ACCEPT, parse_nfl),
        "tennis": (ATP_URL, JSON_ACCEPT, parse_tennis),
        "cricket": (CRICKET_URL, XML_ACCEPT, parse_cricket),
    }
    pool = ThreadPoolExecutor(max_workers=len(jobs))
    try:
        futures = {s: pool.submit(_read, url, accept, parse, get) for s, (url, accept, parse) in jobs.items()}
        wait(futures.values(), timeout=WAIT_SECONDS)
        sports = {s: f.result() if f.done() else {"ok": False, "entries": []} for s, f in futures.items()}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # a stalled request is abandoned, not waited for
    good = sum(v["ok"] for v in sports.values())
    if good * 2 < len(sports):  # a mostly failed run must not replace a good file (same rule as the feed)
        raise ScoresError(f"only {good} of {len(sports)} sports could be read; keeping the previous file")
    return {"generated": now.isoformat(timespec="seconds"), **sports}
