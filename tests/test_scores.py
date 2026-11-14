import json
import threading
from datetime import UTC, datetime
from typing import Any

import pytest

from ingest import scores
from ingest.feeds import FeedError
from ingest.scores import ScoresError, build_scores, parse_cricket, parse_nfl, parse_tennis

NOW = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)


def competitor(side: str, name: str, score: Any = "0") -> dict[str, Any]:
    return {"homeAway": side, "score": score, "team": {"displayName": name}}


def game(gid: str, state: str, date: str, home: Any = None, away: Any = None, **over: Any) -> dict[str, Any]:
    kind = {"pre": "STATUS_SCHEDULED", "in": "STATUS_IN_PROGRESS", "post": "STATUS_FINAL"}[state]
    return {
        "id": gid,
        "date": date,
        "status": {"type": {"state": state, "name": kind, "shortDetail": f"detail {gid}"}},
        "competitions": [
            {"competitors": [home or competitor("home", f"Home {gid}", "21"), away or competitor("away", f"Away {gid}", "14")]}
        ],
        "links": [
            {"rel": ["boxscore", "desktop"], "href": "https://example.com/box"},
            {"rel": ["summary", "desktop", "event"], "href": f"https://example.com/game/{gid}"},
        ],
        **over,
    }


def nfl_doc(*events: dict[str, Any]) -> bytes:
    return json.dumps({"events": list(events)}).encode()


def test_parse_nfl_reads_a_game() -> None:
    (g,) = parse_nfl(nfl_doc(game("1", "post", "2026-11-13T01:15Z")))
    assert g == {
        "id": "1",
        "state": "final",
        "detail": "detail 1",
        "start": "2026-11-13T01:15Z",
        "home": {"name": "Home 1", "score": 21},
        "away": {"name": "Away 1", "score": 14},
        "url": "https://example.com/game/1",
    }


def test_parse_nfl_orders_live_then_upcoming_then_final() -> None:
    got = parse_nfl(
        nfl_doc(
            game("old", "post", "2026-11-09T18:00Z"),
            game("new", "post", "2026-11-12T18:00Z"),
            game("late", "pre", "2026-11-17T18:00Z"),
            game("soon", "pre", "2026-11-15T18:00Z"),
            game("now", "in", "2026-11-13T14:00Z"),
        )
    )
    assert [g["id"] for g in got] == ["now", "soon", "late", "new", "old"]
    assert got[0]["state"] == "live"


def test_parse_nfl_tolerates_missing_scores_links_and_unknown_state() -> None:
    odd = game("1", "pre", "2026-11-13T01:15Z", home=competitor("home", "H", None), away=competitor("away", "A", "x"), links=None)
    odd["status"]["type"]["state"] = "mystery"
    (g,) = parse_nfl(nfl_doc(odd))
    assert g["home"]["score"] is None and g["away"]["score"] is None and g["url"] is None and g["state"] == "pre"


def test_parse_nfl_keeps_only_web_links() -> None:
    bad = game(
        "1", "post", "2026-11-13T01:15Z", links=[{"rel": ["summary"], "href": "javascript:alert(1)"}, "nope", {"rel": None}]
    )
    assert parse_nfl(nfl_doc(bad))[0]["url"] is None
    not_text = game("2", "post", "2026-11-13T01:15Z", links=[{"rel": ["summary"], "href": 5}])
    assert parse_nfl(nfl_doc(not_text))[0]["url"] is None


def test_parse_nfl_skips_a_malformed_game_and_keeps_the_rest() -> None:
    got = parse_nfl(nfl_doc({}, {"id": "x", "competitions": []}, None, game("ok", "post", "2026-11-13T01:15Z")))  # type: ignore[arg-type]
    assert [g["id"] for g in got] == ["ok"]


def test_parse_nfl_is_capped() -> None:
    got = parse_nfl(nfl_doc(*[game(str(i), "post", f"2026-11-13T01:{i:02d}Z") for i in range(30)]))
    assert len(got) == scores.MAX_PER_SPORT


@pytest.mark.parametrize("body", [b"nope", b"[]", b"{}", b'{"events": 5}'])
def test_parse_nfl_rejects_bad_input(body: bytes) -> None:
    with pytest.raises(ScoresError):
        parse_nfl(body)


def player(name: str, order: int, sets: list[Any], winner: bool = False) -> dict[str, Any]:
    return {"order": order, "winner": winner, "athlete": {"displayName": name}, "linescores": [{"value": v} for v in sets]}


def match(mid: str, state: str, date: str, players: Any = None, **over: Any) -> dict[str, Any]:
    return {
        "id": mid,
        "date": date,
        "status": {"type": {"state": state, "description": "Final" if state == "post" else "Scheduled"}},
        "competitors": players or [player("Player B", 2, [7.0, 4.0, 7.0], True), player("Player A", 1, [5.0, 6.0, 6.0])],
        **over,
    }


def tennis_doc(*matches: dict[str, Any], name: str = "Example Open") -> bytes:
    return json.dumps({"events": [{"name": name, "groupings": [{"competitions": list(matches)}]}]}).encode()


def test_parse_tennis_reads_a_match() -> None:
    (m,) = parse_tennis(tennis_doc(match("7", "post", "2026-11-07T10:00Z", startDate="2026-11-07T11:00Z")))
    assert m == {
        "id": "7",
        "state": "final",
        "detail": "Final",
        "start": "2026-11-07T11:00Z",
        "tournament": "Example Open",
        "players": [
            {"name": "Player A", "sets": [5, 6, 6], "winner": False},
            {"name": "Player B", "sets": [7, 4, 7], "winner": True},
        ],
    }


def test_parse_tennis_orders_like_nfl_and_uses_date_when_no_start_date() -> None:
    got = parse_tennis(
        tennis_doc(
            match("done", "post", "2026-11-07T10:00Z"),
            match("soon", "pre", "2026-11-15T10:00Z"),
            match("live", "in", "2026-11-13T10:00Z"),
        )
    )
    assert [m["id"] for m in got] == ["live", "soon", "done"] and got[0]["start"] == "2026-11-13T10:00Z"


def test_parse_tennis_handles_tournaments_without_groupings_and_bad_matches() -> None:
    body = json.dumps(
        {
            "events": [
                {"name": "No groups"},
                {
                    "name": "Bad",
                    "groupings": [{"competitions": [{}, match("x", "post", "2026-11-07T10:00Z", players=[{}]), None]}],
                },
                {"name": "Fine", "groupings": [{}, {"competitions": [match("ok", "post", "2026-11-07T10:00Z")]}]},
            ]
        }
    ).encode()
    assert [m["id"] for m in parse_tennis(body)] == ["ok"]


def test_parse_tennis_is_capped() -> None:
    got = parse_tennis(tennis_doc(*[match(str(i), "post", f"2026-11-07T10:{i:02d}Z") for i in range(30)]))
    assert len(got) == scores.MAX_PER_SPORT


@pytest.mark.parametrize("body", [b"nope", b"{}", b'{"events": 5}', b'{"events": [5]}'])
def test_parse_tennis_rejects_bad_input(body: bytes) -> None:
    with pytest.raises(ScoresError):
        parse_tennis(body)


CRICKET = b"""<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0"><channel><title>Live Scores</title>
<item><title>Team A 204/10 &amp;  410/10  v Team B 325/10 &amp;  50/2 *</title>
<link>http://www.example.com/match/1.html?CMP=OTC-RSS </link><guid>http://www.example.com/match/1.html</guid></item>
<item><title>Team C 348/10  v Team D 133/10</title><link>javascript:alert(1)</link></item>
<item><title></title><link>http://www.example.com/match/3.html</link></item>
</channel></rss>"""


def test_parse_cricket_reads_score_lines() -> None:
    a, b = parse_cricket(CRICKET)
    assert a == {
        "id": "http://www.example.com/match/1.html",
        "line": "Team A 204/10 & 410/10 v Team B 325/10 & 50/2 *",
        "live": True,
        "url": "http://www.example.com/match/1.html?CMP=OTC-RSS",
    }
    assert b["line"] == "Team C 348/10 v Team D 133/10" and b["live"] is False and b["url"] is None
    assert b["id"] == b["line"]  # no usable guid or link: the line identifies it


def test_parse_cricket_id_stays_the_same_when_the_score_changes() -> None:
    def one(score: str, guid: str = "<guid>http://www.example.com/match/9.html</guid>") -> dict[str, Any]:
        body = f"<rss><channel><item><title>Team A {score} v Team B 3/0</title>{guid}</item></channel></rss>"
        return parse_cricket(body.encode())[0]

    assert one("10/1")["id"] == one("250/4")["id"] == "http://www.example.com/match/9.html"
    link_only = "<link>http://www.example.com/match/9.html</link>"
    assert one("10/1", link_only)["id"] == one("250/4", link_only)["id"] == "http://www.example.com/match/9.html"


def test_parse_cricket_is_capped() -> None:
    items = "".join(f"<item><title>Team {i} 1/0 v Other 2/0</title></item>" for i in range(30))
    assert len(parse_cricket(f"<rss><channel>{items}</channel></rss>".encode())) == scores.MAX_PER_SPORT


@pytest.mark.parametrize(
    "body",
    [
        b"not xml",
        b'<!DOCTYPE rss [<!ENTITY x "y">]><rss><channel><item><title>&x;</title></item></channel></rss>',
        "<?xml version='1.0' encoding='UTF-16'?><rss/>".encode("utf-16"),
    ],
)
def test_parse_cricket_refuses_unsafe_or_broken_xml(body: bytes) -> None:
    with pytest.raises(ScoresError):
        parse_cricket(body)


def make_getter(answers: dict[str, bytes | Exception]) -> Any:
    def get(url: str, accept: str) -> bytes:
        for key, value in answers.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise FeedError("fetch failed: 404")

    return get


GOOD = {
    "nfl": nfl_doc(game("1", "post", "2026-11-13T01:15Z")),
    "atp": tennis_doc(match("7", "post", "2026-11-07T10:00Z")),
    "livescores": CRICKET,
}


def test_build_scores_reports_every_sport() -> None:
    doc = build_scores(getter=make_getter(GOOD), now=NOW)
    assert doc["generated"] == "2026-11-13T15:00:00+00:00"
    assert [len(doc[s]["entries"]) for s in ("nfl", "tennis", "cricket")] == [1, 1, 2]
    assert all(doc[s]["ok"] for s in ("nfl", "tennis", "cricket"))


def test_one_failing_sport_does_not_hide_the_others() -> None:
    doc = build_scores(getter=make_getter({**GOOD, "atp": b"garbage"}), now=NOW)
    assert doc["tennis"] == {"ok": False, "entries": []}
    assert doc["nfl"]["ok"] is True and doc["cricket"]["ok"] is True


def test_build_scores_raises_when_nothing_could_be_read() -> None:
    with pytest.raises(ScoresError, match="previous file"):
        build_scores(getter=make_getter({}), now=NOW)


def test_a_mostly_failed_run_keeps_the_previous_file() -> None:
    with pytest.raises(ScoresError, match="only 1 of 3"):
        build_scores(getter=make_getter({"nfl": GOOD["nfl"]}), now=NOW)


def test_start_times_sort_by_the_moment_not_the_text() -> None:
    # same instant spelled three ways, plus a later one and an unparseable one
    got = parse_nfl(
        nfl_doc(
            game("late", "pre", "2026-11-15T10:00:30+00:00"),
            game("a", "pre", "2026-11-15T10:00Z"),
            game("z", "pre", "2026-11-15T05:00:00-05:00"),  # 10:00 UTC
            game("junk", "pre", "soon"),
            game("naive", "pre", "2026-11-15T09:00:00"),  # no zone: UTC
        )
    )
    assert [g["id"] for g in got][:2] == ["junk", "naive"]
    assert [g["id"] for g in got][-1] == "late"


def test_a_stalled_request_times_out_instead_of_hanging(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()
    monkeypatch.setattr(scores, "WAIT_SECONDS", 0.05)

    def get(url: str, accept: str) -> bytes:
        if "atp" in url:
            release.wait(5)
            return b""
        return GOOD["livescores"] if "livescores" in url else GOOD["nfl"]

    doc = build_scores(getter=get, now=NOW)
    release.set()
    assert doc["tennis"]["ok"] is False and doc["nfl"]["ok"] is True and doc["cricket"]["ok"] is True


def test_default_getter_uses_the_right_accept_and_a_short_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_fetch(url: str, **kw: Any) -> bytes:
        calls.append((url, kw))
        return CRICKET if "livescores" in url else nfl_doc()

    monkeypatch.setattr(scores, "fetch", fake_fetch)
    build_scores(now=NOW)
    assert len(calls) == 3
    assert sorted(kw["accept"] for _, kw in calls) == sorted([scores.JSON_ACCEPT, scores.JSON_ACCEPT, scores.XML_ACCEPT])
    assert all(kw["deadline_seconds"] == scores.DEADLINE_SECONDS for _, kw in calls)
