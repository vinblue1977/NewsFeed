"""Weather alert pushes: severity rule, the registration switch, ended alerts, quiet hours, caps, dedupe."""

import json
from datetime import timedelta
from typing import Any

import pytest
from test_push import NOW, FakeS3, Recorder, cluster, config, feed_of, reg

from ingest import push
from ingest.push import run_push


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    monkeypatch.setenv("DATA_PREFIX", "data")
    push.reset_config_cache()


def alert(
    aid: str = "a1", severity: str = "Severe", event: str = "Tornado Warning", ends_hours: float | None = 2
) -> dict[str, Any]:
    return {
        "id": aid,
        "event": event,
        "severity": severity,
        "headline": f"{event} issued for the county",
        "instruction": "Take shelter now.",
        "ends": (NOW + timedelta(hours=ends_hours)).isoformat() if ends_hours is not None else "",
    }


def ready() -> FakeS3:
    """A push state that has already seeded the weather alerts, so new ones are pushed."""
    return FakeS3({"data/push-abc.json": json.dumps({"sent": {}, "days": {}, "wx_seeded": NOW.isoformat()}).encode()})


def wx(*alerts: dict[str, Any]) -> dict[str, Any]:
    return {"alerts": list(alerts), "alerts_ok": True}


def test_a_severe_alert_becomes_a_notification() -> None:
    [note] = push.weather_alerts(wx(alert(event="E" * 300)), reg(), {}, NOW)
    assert note.kind == "weather" and note.id == "wx:a1" and note.url == "/"
    assert len(note.title) == push.TITLE_CHARS and len(note.body) == push.BODY_CHARS
    assert note.payload()["tag"] == "wx:a1"


def test_only_severe_and_extreme_qualify_extreme_first() -> None:
    doc = wx(alert("m", "Moderate"), alert("s", "Severe"), alert("x", "Extreme"), alert("u", "Unknown"), alert("n", "Minor"))
    assert [n.id for n in push.weather_alerts(doc, reg(), {}, NOW)] == ["wx:x", "wx:s"]


def test_off_ended_sent_and_malformed_alerts_are_left_out() -> None:
    assert push.weather_alerts(wx(alert()), reg(weather=False), {}, NOW) == []
    assert push.weather_alerts(None, reg(), {}, NOW) == []
    assert push.weather_alerts(wx(alert(ends_hours=-1)), reg(), {}, NOW) == []
    assert push.weather_alerts(wx(alert()), reg(), {"wx:a1": NOW.isoformat()}, NOW) == []
    assert [n.id for n in push.weather_alerts(wx(alert(ends_hours=None)), reg(), {}, NOW)] == [
        "wx:a1"
    ]  # no end time: still active
    junk: dict[str, Any] = {"alerts": ["x", {"severity": "Severe"}, {"id": "z", "severity": "Severe"}]}
    assert [n.id for n in push.weather_alerts(junk, reg(), {}, NOW)] == ["wx:z"]
    assert push.weather_alerts({"alerts": None}, reg(), {}, NOW) == []


def test_weather_goes_through_quiet_hours_and_does_not_use_the_daily_cap() -> None:
    night = NOW.replace(hour=8)  # 02:00 in Chicago: quiet
    day = night.astimezone(reg().tz).strftime("%Y-%m-%d")
    s3 = FakeS3({"data/push-abc.json": json.dumps({"sent": {}, "days": {day: 5}, "wx_seeded": NOW.isoformat()}).encode()})
    sender = Recorder()
    assert run_push(s3, feed_of(cluster("big")), now=night, config=config(), sender=sender, weather=wx(alert())) == "sent:1"
    assert [m["tag"] for m in sender.calls] == ["wx:a1"]  # the capped news story stayed home, the warning did not
    state = json.loads(s3.puts[-1]["Body"])
    assert set(state["sent"]) == {"wx:a1", "wxe:Tornado Warning"} and sum(state["days"].values()) == 5  # not counted


def test_quiet_hours_without_a_severe_alert_stay_quiet_and_an_alert_is_sent_once() -> None:
    night = NOW.replace(hour=8)
    assert (
        run_push(ready(), feed_of(), now=night, config=config(), sender=Recorder(), weather=wx(alert("m", "Moderate"))) == "quiet"
    )
    s3, sender = ready(), Recorder()
    assert run_push(s3, feed_of(), now=NOW, config=config(), sender=sender, weather=wx(alert())) == "sent:1"
    assert run_push(s3, feed_of(), now=NOW + timedelta(minutes=15), config=config(), sender=sender, weather=wx(alert())) == "none"
    assert len(sender.calls) == 1


def test_weather_goes_before_news_but_leaves_one_slot_for_it() -> None:
    feed = feed_of(cluster("a"), cluster("b"))
    sender = Recorder()
    status = run_push(
        ready(), feed, now=NOW, config=config(), sender=sender, weather=wx(alert("w1", event="A"), alert("w2", event="B"))
    )
    assert status == "sent:2" and [m["tag"] for m in sender.calls] == ["wx:w1", "a"]  # one warning, one story
    sender = Recorder()  # no news waiting: both warnings go
    run_push(
        ready(), feed_of(), now=NOW, config=config(), sender=sender, weather=wx(alert("w1", event="A"), alert("w2", event="B"))
    )
    assert [m["tag"] for m in sender.calls] == ["wx:w1", "wx:w2"]


def test_a_reissued_warning_under_a_new_id_is_not_pushed_again_for_six_hours() -> None:
    s3, sender = ready(), Recorder()
    run_push(s3, feed_of(), now=NOW, config=config(), sender=sender, weather=wx(alert("v1")))
    later = NOW + timedelta(minutes=30)
    assert run_push(s3, feed_of(), now=later, config=config(), sender=sender, weather=wx(alert("v2"))) == "none"
    assert (
        run_push(
            s3, feed_of(), now=NOW + timedelta(hours=7), config=config(), sender=sender, weather=wx(alert("v3", ends_hours=9))
        )
        == "sent:1"
    )
    assert [m["tag"] for m in sender.calls] == ["wx:v1", "wx:v3"]


def test_the_first_run_marks_active_alerts_sent_instead_of_pushing_them() -> None:
    s3, sender = FakeS3(), Recorder()
    first = run_push(s3, feed_of(), now=NOW, config=config(), sender=sender, weather=wx(alert("old")))
    assert first == "none" and sender.calls == []
    state = json.loads(s3.puts[-1]["Body"])
    assert "wx:old" in state["sent"] and "wx_seeded" in state
    assert (
        run_push(
            s3,
            feed_of(),
            now=NOW + timedelta(minutes=15),
            config=config(),
            sender=sender,
            weather=wx(alert("old"), alert("new", event="Flood Warning")),
        )
        == "sent:1"
    )
    assert [m["tag"] for m in sender.calls] == ["wx:new"]


def test_a_failed_alerts_read_does_not_seed() -> None:
    s3 = FakeS3()
    run_push(s3, feed_of(), now=NOW, config=config(), sender=Recorder(), weather={"alerts": [], "alerts_ok": False})
    assert not s3.puts or "wx_seeded" not in json.loads(s3.puts[-1]["Body"])


def test_a_long_lived_warning_keeps_its_dedupe_entry_past_three_days() -> None:
    old = (NOW - timedelta(days=5)).isoformat()
    doc = {"sent": {"wx:heat": old, "alert:x": old}, "days": {}, "wx_seeded": old}
    state = push.load_state(FakeS3({"data/s.json": json.dumps(doc).encode()}), "s", NOW)
    assert "wx:heat" in state["sent"] and "alert:x" not in state["sent"] and state["wx_seeded"] == old
