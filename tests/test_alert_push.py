"""Village alert pushes: the registration switch, the rule (alert feeds only, under two days old, once), quiet hours, caps."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from test_push import KEY, NOW, FakeS3, Recorder, cluster, config, feed_of, reg

from ingest import push
from ingest.push import run_push


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    monkeypatch.setenv("DATA_PREFIX", "data")
    push.reset_config_cache()


def item(iid: str, *, age_hours: float = 1, title: str = "Boil water notice", source: str = "village.example") -> dict[str, Any]:
    return {
        "id": iid,
        "title": title,
        "source": source,
        "published": (NOW - timedelta(hours=age_hours)).isoformat(),
        "topic": "local",
    }


def feed_with(*items: dict[str, Any], clusters: tuple[dict[str, Any], ...] = ()) -> dict[str, Any]:
    base = feed_of(*clusters)
    return {"items": [*base["items"], *items], "clusters": base["clusters"]}


def ready() -> FakeS3:
    """A push state that has already seen the alert feeds (see test_the_first_run...), so new items are pushed."""
    state = {"sent": {}, "days": {}, "seeded": (NOW - timedelta(days=1)).isoformat()}
    return FakeS3({"data/push-abc.json": json.dumps(state).encode()})


def test_a_registration_without_the_alerts_field_gets_them_and_false_turns_them_off() -> None:
    assert reg().alerts is True  # registrations made before the field existed keep working
    assert reg(alerts=True).alerts is True
    assert reg(alerts=False).alerts is False


def test_an_alert_item_is_pushed_with_its_own_id_title_body_and_reader_link() -> None:
    feed = feed_with(item("abc", title="X" * 300, source="S" * 300))
    [note] = push.village_alerts(feed, reg(), {}, NOW, {"abc"})
    assert note.kind == "alert" and note.id == "alert:abc" and note.topic == "local"
    assert len(note.title) == push.TITLE_CHARS and len(note.body) == push.BODY_CHARS
    assert note.url == "/#/read/abc"
    assert note.payload()["tag"] == "alert:abc"


def test_only_items_from_the_alert_feeds_qualify() -> None:
    feed = feed_with(item("alert1"), item("ordinary"))
    assert [n.id for n in push.village_alerts(feed, reg(), {}, NOW, {"alert1"})] == ["alert:alert1"]
    assert push.village_alerts(feed, reg(), {}, NOW, set()) == []


def test_age_limit_is_two_days_and_unreadable_dates_are_dropped() -> None:
    feed = feed_with(item("new", age_hours=47), item("old", age_hours=49))
    feed["items"].append({"id": "bad", "title": "t", "source": "s", "published": "not a time"})
    assert [n.id for n in push.village_alerts(feed, reg(), {}, NOW, {"new", "old", "bad"})] == ["alert:new"]


def test_newest_first_and_already_sent_are_left_out() -> None:
    feed = feed_with(item("a", age_hours=5), item("b", age_hours=1), item("c", age_hours=3))
    assert [n.id for n in push.village_alerts(feed, reg(), {}, NOW, {"a", "b", "c"})] == ["alert:b", "alert:c", "alert:a"]
    assert [n.id for n in push.village_alerts(feed, reg(), {"alert:b": NOW.isoformat()}, NOW, {"a", "b", "c"})] == [
        "alert:c",
        "alert:a",
    ]


def test_the_alerts_switch_turns_the_rule_off() -> None:
    assert push.village_alerts(feed_with(item("a")), reg(alerts=False), {}, NOW, {"a"}) == []


def test_alert_ids_never_collide_with_cluster_ids() -> None:
    feed = feed_with(item("a"), clusters=(cluster("a", sources=9),))
    assert sorted(n.id for n in push.candidates(feed, reg(), {}, NOW, {"a"})) == ["a", "alert:a"]
    assert [n.id for n in push.candidates(feed, reg(), {"a": NOW.isoformat()}, NOW, {"a"})] == [
        "alert:a"
    ]  # a cluster id is not an alert id


def test_alerts_go_before_breaking_stories() -> None:
    feed = feed_with(item("a"), clusters=(cluster("big", sources=9),))
    assert [n.id for n in push.candidates(feed, reg(), {}, NOW, {"a"})] == ["alert:a", "big"]


def test_run_sends_an_alert_once_and_marks_it() -> None:
    feed = feed_with(item("a"))
    s3, sender = ready(), Recorder()
    assert run_push(s3, feed, {"a"}, now=NOW, config=config(), sender=sender) == "sent:1"
    assert [m["tag"] for m in sender.calls] == ["alert:a"] and sender.calls[0]["url"] == "/#/read/a"
    assert set(json.loads(s3.puts[-1]["Body"])["sent"]) == {"alert:a"}
    assert run_push(s3, feed, {"a"}, now=NOW + timedelta(minutes=15), config=config(), sender=Recorder()) == "none"


def test_alerts_go_through_quiet_hours_but_breaking_stories_do_not() -> None:
    night = datetime(2026, 11, 18, 5, 0, tzinfo=UTC)  # 23:00 in Chicago
    breaking = cluster("big", sources=9)
    breaking["published"] = (night - timedelta(minutes=10)).isoformat()
    fresh = {**item("a"), "published": (night - timedelta(hours=1)).isoformat()}
    feed = feed_with(fresh, clusters=(breaking,))
    s3, sender = ready(), Recorder()
    assert run_push(s3, feed, {"a"}, now=night, config=config(), sender=sender) == "sent:1"
    assert [m["tag"] for m in sender.calls] == ["alert:a"]  # the breaking story waits for the morning
    assert "big" not in json.loads(s3.puts[-1]["Body"])["sent"]


def test_quiet_with_nothing_to_alert_stays_quiet_and_writes_nothing() -> None:
    night = datetime(2026, 11, 18, 5, 0, tzinfo=UTC)
    s3 = FakeS3()
    assert run_push(s3, feed_with(item("a")), set(), now=night, config=config(), sender=Recorder()) == "quiet"
    assert run_push(s3, feed_with(item("a")), {"a"}, now=night, config=config(alerts=False), sender=Recorder()) == "quiet"
    assert s3.puts == []
    done = ready()  # the alert feeds are known and the only item was already sent: quiet, not "none"
    done.files["data/push-abc.json"] = json.dumps(
        {"sent": {"alert:a": NOW.isoformat()}, "days": {}, "seeded": NOW.isoformat()}
    ).encode()
    sender = Recorder()
    assert run_push(done, feed_with(item("a")), {"a"}, now=night, config=config(), sender=sender) == "quiet"
    assert sender.calls == []


def test_the_first_run_with_alert_feeds_marks_what_they_already_hold_as_sent_without_pushing() -> None:
    feed = feed_with(item("old1", age_hours=30), item("old2", age_hours=2))
    s3, sender = FakeS3(), Recorder()
    assert run_push(s3, feed, {"old1", "old2"}, now=NOW, config=config(), sender=sender) == "none"
    assert sender.calls == []  # no backlog burst, whatever the hour
    state = json.loads(s3.puts[-1]["Body"])
    assert set(state["sent"]) == {"alert:old1", "alert:old2"} and "seeded" in state and state["days"] == {}
    later = feed_with(*feed["items"], item("fresh", age_hours=0.1))
    assert (
        run_push(s3, later, {"old1", "old2", "fresh"}, now=NOW + timedelta(minutes=15), config=config(), sender=sender)
        == "sent:1"
    )
    assert [m["tag"] for m in sender.calls] == ["alert:fresh"]  # only what appears afterwards


def test_seeding_waits_until_alerts_are_wanted_and_a_failed_save_does_not_stop_the_run() -> None:
    s3 = FakeS3()
    run_push(s3, feed_with(item("a")), {"a"}, now=NOW, config=config(alerts=False), sender=Recorder())
    assert s3.puts == []  # alerts are off: nothing is seeded or sent
    broken = FakeS3(write_error=OSError("denied"))
    assert run_push(broken, feed_with(item("a")), {"a"}, now=NOW, config=config(), sender=Recorder()) == "none"


def test_an_item_missing_fields_is_skipped_or_titled_empty_and_never_breaks_the_push_step() -> None:
    feed = {"items": [{"id": "a", "published": NOW.isoformat()}, {"published": NOW.isoformat()}, {"id": "b"}], "clusters": []}
    [note] = push.village_alerts(feed, reg(), {}, NOW, {"a", "b"})
    assert note.id == "alert:a" and note.title == ""


def test_alerts_share_the_per_run_and_per_day_caps() -> None:
    feed = feed_with(*[item(f"n{i}", age_hours=1 + i / 10) for i in range(7)])
    ids = {f"n{i}" for i in range(7)}
    s3 = ready()
    sent = 0
    for minutes in (0, 15, 30, 45):
        sender = Recorder()
        run_push(s3, feed, ids, now=NOW + timedelta(minutes=minutes), config=config(), sender=sender)
        assert len(sender.calls) <= push.PER_RUN
        sent += len(sender.calls)
    assert sent == push.PER_DAY  # two, two, one, then the day is full


def test_an_expired_subscription_stops_the_alerts_like_any_push() -> None:
    sender = Recorder(push.webpush.Expired())
    assert run_push(ready(), feed_with(item("a")), {"a"}, now=NOW, config=config(), sender=sender) == "expired"
    assert KEY is not None  # the shared signing key from test_push is used by Recorder
