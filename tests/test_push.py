"""Breaking-story pushes: registration, the qualifying rule, quiet hours, caps, dedupe, state, and failure handling."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from ingest import push, webpush
from ingest.push import Config, Registration, parse_registration, run_push

NOW = datetime(2026, 11, 17, 18, 0, tzinfo=UTC)  # noon in Chicago (CST, UTC-6)
SITE = "https://news.example.net"
SUBSCRIPTION = {"endpoint": "https://web.push.apple.com/abc", "keys": {"p256dh": "BPkey", "auth": "authsecret"}}


def registration(**prefs: Any) -> str:
    base = {
        "topics": ["us", "world", "india", "sports", "local"],
        "weather": True,
        "quiet": {"start": "22:00", "end": "07:00"},
        "tz": "America/Chicago",
    }
    return json.dumps({"v": 1, "site": "https://news.example.net/", "subscription": SUBSCRIPTION, "prefs": {**base, **prefs}})


def reg(**prefs: Any) -> Registration:
    parsed = parse_registration(registration(**prefs))
    assert parsed is not None
    return parsed


def cluster(
    cid: str,
    *,
    sources: int = 7,
    topic: str = "us",
    age_minutes: int = 30,
    title: str = "Big story",
    lead_source: str = "BBC News",
) -> dict[str, Any]:
    return {
        "id": cid,
        "title": title,
        "topic": topic,
        "lead": f"lead-{cid}",
        "published": (NOW - timedelta(minutes=age_minutes)).isoformat(),
        "sources": sources,
        "items": [f"lead-{cid}"],
        "_source": lead_source,
    }


def feed_of(*clusters: dict[str, Any]) -> dict[str, Any]:
    items = [{"id": c["lead"], "source": c["_source"], "title": c["title"]} for c in clusters]
    return {"items": items, "clusters": [{k: v for k, v in c.items() if k != "_source"} for c in clusters]}


# ---- registration


def test_registration_parses_the_contract() -> None:
    r = reg()
    assert r.subscription == SUBSCRIPTION
    assert r.topics == {"us", "world", "india", "sports", "local"}
    assert r.weather is True and r.quiet == (22 * 60, 7 * 60) and r.tz == ZoneInfo("America/Chicago")
    assert r.site == "https://news.example.net"  # no trailing slash


def test_registration_defaults() -> None:
    minimal = parse_registration(json.dumps({"v": 1, "site": "https://news.example.net", "subscription": SUBSCRIPTION}))
    assert minimal is not None
    assert (
        minimal.quiet == push.DEFAULT_QUIET
        and minimal.weather is False
        and "us" in minimal.topics
        and minimal.tz == ZoneInfo("UTC")
    )


def test_registration_quiet_can_be_switched_off_or_ignored_when_malformed() -> None:
    assert reg(quiet=None).quiet is None
    assert reg(quiet={"start": "25:00", "end": "07:00"}).quiet == push.DEFAULT_QUIET
    assert reg(quiet="never").quiet == push.DEFAULT_QUIET


def test_registration_drops_unknown_topics() -> None:
    assert reg(topics=["us", "weird"]).topics == {"us"}


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json",
        "[]",
        json.dumps({"v": 2, "site": SITE, "subscription": SUBSCRIPTION}),
        json.dumps({"v": 1, "site": SITE}),
        json.dumps(
            {"v": 1, "site": SITE, "subscription": {"endpoint": "https://example.com/x", "keys": {"p256dh": "a", "auth": "b"}}}
        ),
        json.dumps(
            {
                "v": 1,
                "site": SITE,
                "subscription": {"endpoint": "https://web.push.apple.com/x", "keys": {"p256dh": 1, "auth": "b"}},
            }
        ),
        json.dumps({"v": 1, "site": SITE, "subscription": SUBSCRIPTION, "prefs": {"topics": "us"}}),
        json.dumps({"v": 1, "site": SITE, "subscription": SUBSCRIPTION, "prefs": {"tz": "Not/AZone"}}),
        json.dumps({"v": 1, "subscription": SUBSCRIPTION}),  # no site, and none in the environment
        json.dumps({"v": 1, "site": "http://news.example.net", "subscription": SUBSCRIPTION}),
        json.dumps({"v": 1, "site": "https://", "subscription": SUBSCRIPTION}),
        json.dumps({"v": 1, "site": 5, "subscription": SUBSCRIPTION}),
    ],
)
def test_invalid_registration_is_none_and_never_logs_the_value(raw: str, caplog: pytest.LogCaptureFixture) -> None:
    assert parse_registration(raw) is None
    assert "web.push.apple.com" not in caplog.text and "authsecret" not in caplog.text


# ---- quiet hours


@pytest.mark.parametrize(
    ("utc_hour", "quiet"),
    [(3, False), (4, True), (5, True), (12, True), (13, False), (14, False)],  # Chicago is UTC-6: 22:00 = 04:00Z, 07:00 = 13:00Z
)
def test_quiet_hours_cross_midnight_in_the_registered_time_zone(utc_hour: int, quiet: bool) -> None:
    assert push.in_quiet(datetime(2026, 11, 17, utc_hour, 0, tzinfo=UTC), reg()) is quiet


def test_quiet_window_inside_one_day_and_equal_bounds_and_none() -> None:
    day = reg(quiet={"start": "13:00", "end": "15:00"}, tz="UTC")
    assert push.in_quiet(datetime(2026, 11, 17, 14, 0, tzinfo=UTC), day) is True
    assert push.in_quiet(datetime(2026, 11, 17, 15, 0, tzinfo=UTC), day) is False
    assert push.in_quiet(NOW, reg(quiet={"start": "08:00", "end": "08:00"})) is False
    assert push.in_quiet(NOW, reg(quiet=None)) is False


def test_other_time_zone_shifts_the_window() -> None:
    tokyo = reg(tz="Asia/Tokyo")  # 18:00Z = 03:00 next day in Tokyo: quiet
    assert push.in_quiet(NOW, tokyo) is True


# ---- the rule


def titles(notes: list[push.Notification]) -> list[str]:
    return [n.id for n in notes]


def test_six_outlets_within_two_hours_qualifies() -> None:
    feed = feed_of(
        cluster("a", sources=6),
        cluster("b", sources=5),
        cluster("c", sources=8, age_minutes=119),
        cluster("d", sources=9, age_minutes=120),
    )
    assert titles(push.breaking(feed, reg(), {}, NOW)) == ["c", "a"]  # most outlets first; five is too few; two hours is too old


def test_a_trusted_breaking_headline_qualifies_with_few_outlets() -> None:
    feed = feed_of(
        cluster("a", sources=2, title="BREAKING: Quake hits coast"),
        cluster("b", sources=1, title="Developing - Storm nears", lead_source="NPR"),
        cluster("c", sources=1, title="LIVE | Election night"),
        cluster("d", sources=2, title="Breaking news: from a blog", lead_source="Some Blog"),
        cluster("e", sources=2, title="Breaking down the budget"),
        cluster("f", sources=2, title="Livestream tips"),
    )
    found = push.breaking(feed, reg(), {}, NOW)
    assert sorted(titles(found)) == ["a", "b", "c"]


def test_payload_shape_and_urls() -> None:
    feed = feed_of(
        cluster("many", sources=7, title="X" * 300), cluster("one", sources=1, title="BREAKING: Solo", lead_source="NPR")
    )
    many, one = sorted(push.breaking(feed, reg(), {}, NOW), key=lambda n: n.id)
    assert many.payload() == {"title": "X" * 140, "body": "7 outlets · BBC News", "url": "/#/story/many", "tag": "many"}
    assert one.payload()["url"] == "/#/read/lead-one" and one.payload()["body"] == "NPR" and one.payload()["tag"] == "one"


def test_topics_must_be_switched_on_and_local_is_off_unless_listed() -> None:
    feed = feed_of(cluster("a", topic="local"), cluster("b", topic="tech"), cluster("c", topic="us"))
    assert titles(push.breaking(feed, reg(topics=["us", "world"]), {}, NOW)) == ["c"]
    assert sorted(titles(push.breaking(feed, reg(topics=["us", "local"]), {}, NOW))) == ["a", "c"]


def test_sent_clusters_are_skipped_and_bad_dates_ignored() -> None:
    feed = feed_of(cluster("a"), cluster("b"))
    feed["clusters"][1]["published"] = "garbage"
    assert titles(push.breaking(feed, reg(), {"a": NOW.isoformat()}, NOW)) == []
    assert titles(push.candidates(feed, reg(), {}, NOW)) == ["a"]


# ---- state


class FakeS3:
    def __init__(
        self, files: dict[str, bytes] | None = None, *, read_error: Exception | None = None, write_error: Exception | None = None
    ) -> None:
        self.files = files or {}
        self.puts: list[dict[str, Any]] = []
        self.read_error, self.write_error = read_error, write_error

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if self.read_error:
            raise self.read_error
        if Key not in self.files:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        body = self.files[Key]
        return {"Body": type("B", (), {"read": lambda self_: body})()}

    def put_object(self, **kw: Any) -> None:
        if self.write_error:
            raise self.write_error
        self.puts.append(kw)
        self.files[kw["Key"]] = kw["Body"] if isinstance(kw["Body"], bytes) else kw["Body"].encode()


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    monkeypatch.setenv("DATA_PREFIX", "data")
    push.reset_config_cache()


def test_state_prunes_old_entries_and_tolerates_junk() -> None:
    old = (NOW - timedelta(days=4)).isoformat()
    fresh = (NOW - timedelta(days=1)).isoformat()
    doc = {
        "sent": {"old": old, "fresh": fresh, "bad": "nope", "none": None},
        "days": {"2026-11-10": 5, "2026-11-16": 2, "x": "y"},
    }
    s3 = FakeS3({"data/push-x.json": json.dumps(doc).encode()})
    assert push.load_state(s3, "push-x", NOW) == {"sent": {"fresh": fresh}, "days": {"2026-11-16": 2}}


def test_state_is_empty_when_missing_or_not_json_and_other_errors_raise() -> None:
    assert push.load_state(FakeS3(), "push-x", NOW) == {"sent": {}, "days": {}}
    assert push.load_state(FakeS3({"data/push-x.json": b"{oops"}), "push-x", NOW) == {"sent": {}, "days": {}}
    with pytest.raises(ClientError):
        push.load_state(FakeS3(read_error=ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")), "push-x", NOW)


# ---- running

KEY = ec.generate_private_key(ec.SECP256R1())


def config(**prefs: Any) -> Config:
    return Config(reg(**prefs), KEY, "push-abc")


class Recorder:
    def __init__(self, *errors: Exception | None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.errors = list(errors)

    def __call__(self, subscription: dict[str, Any], message: dict[str, str], key: Any, site: str) -> int:
        assert (
            subscription == SUBSCRIPTION and site == "https://news.example.net" and key is KEY
        )  # the registration's site, no trailing slash
        error = self.errors.pop(0) if self.errors else None
        if error:
            raise error
        self.calls.append(message)
        return 201


def test_off_without_configuration() -> None:
    assert run_push(FakeS3(), feed_of(cluster("a")), now=NOW, config=None, sender=Recorder()) == "off"


def test_sends_at_most_two_per_run_marks_them_and_does_not_repeat() -> None:
    feed = feed_of(cluster("a", sources=9), cluster("b", sources=8), cluster("c", sources=7))
    s3, sender = FakeS3(), Recorder()
    assert run_push(s3, feed, now=NOW, config=config(), sender=sender) == "sent:2"
    assert [m["tag"] for m in sender.calls] == ["a", "b"]
    state = json.loads(s3.puts[-1]["Body"])
    assert set(state["sent"]) == {"a", "b"} and state["days"] == {"2026-11-17": 2}
    assert s3.puts[-1]["Key"] == "data/push-abc.json"
    later = Recorder()  # the next run sends only what is left
    assert run_push(s3, feed, now=NOW + timedelta(minutes=15), config=config(), sender=later) == "sent:1"
    assert [m["tag"] for m in later.calls] == ["c"]
    assert run_push(s3, feed, now=NOW + timedelta(minutes=30), config=config(), sender=Recorder()) == "none"


def test_daily_cap_counts_the_local_day() -> None:
    feed = feed_of(*[cluster(f"n{i}", sources=20 - i) for i in range(7)])
    s3 = FakeS3()
    total = 0
    for minutes in (0, 15, 30, 45, 60):
        sender = Recorder()
        run_push(s3, feed, now=NOW + timedelta(minutes=minutes), config=config(), sender=sender)
        total += len(sender.calls)
    assert total == 5  # 2 + 2 + 1, then the day is full
    full = Recorder()
    assert run_push(s3, feed, now=NOW + timedelta(minutes=75), config=config(), sender=full) == "none" and full.calls == []


def test_a_new_local_day_resets_the_count() -> None:
    chicago = {"days": {"2026-11-17": 5}, "sent": {}}
    s3 = FakeS3({"data/push-abc.json": json.dumps(chicago).encode()})
    assert run_push(s3, feed_of(cluster("a")), now=NOW, config=config(), sender=Recorder()) == "none"  # full today
    tomorrow = NOW + timedelta(days=1)
    feed = feed_of(cluster("a", age_minutes=30))
    feed["clusters"][0]["published"] = (tomorrow - timedelta(minutes=30)).isoformat()
    assert run_push(s3, feed, now=tomorrow, config=config(), sender=Recorder()) == "sent:1"


def test_quiet_hours_send_nothing_and_mark_nothing() -> None:
    night = datetime(2026, 11, 18, 5, 0, tzinfo=UTC)  # 23:00 in Chicago
    feed = feed_of(cluster("a"))
    feed["clusters"][0]["published"] = (night - timedelta(minutes=10)).isoformat()
    s3, sender = FakeS3(), Recorder()
    assert run_push(s3, feed, now=night, config=config(), sender=sender) == "quiet"
    assert sender.calls == [] and s3.puts == []
    morning = datetime(2026, 11, 18, 13, 30, tzinfo=UTC)  # 07:30 local, the story is now 90 minutes older
    feed["clusters"][0]["published"] = (morning - timedelta(minutes=90)).isoformat()
    assert run_push(s3, feed, now=morning, config=config(), sender=sender) == "sent:1"  # still under two hours, so it goes
    feed["clusters"][0]["published"] = (morning - timedelta(hours=3)).isoformat()
    assert run_push(FakeS3(), feed, now=morning, config=config(), sender=Recorder()) == "none"  # too old: dropped


def test_an_expired_subscription_stops_the_run_and_logs_clearly(caplog: pytest.LogCaptureFixture) -> None:
    feed = feed_of(cluster("a", sources=9), cluster("b", sources=8))
    s3, sender = FakeS3(), Recorder(webpush.Expired("410"))
    assert run_push(s3, feed, now=NOW, config=config(), sender=sender) == "expired"
    assert sender.calls == [] and s3.puts == []  # nothing marked sent
    assert "register the phone again" in caplog.text


def test_other_send_failures_stop_the_run_without_raising() -> None:
    feed = feed_of(cluster("a", sources=9), cluster("b", sources=8))
    s3, sender = FakeS3(), Recorder(None, webpush.PushError("down"))
    assert run_push(s3, feed, now=NOW, config=config(), sender=sender) == "failed"
    assert [m["tag"] for m in sender.calls] == ["a"]
    assert set(json.loads(s3.puts[-1]["Body"])["sent"]) == {"a"}  # the one that went is remembered
    boom = Recorder(RuntimeError("boom"))
    assert run_push(FakeS3(), feed, now=NOW, config=config(), sender=boom) == "failed"


def test_a_state_write_failure_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    s3 = FakeS3(write_error=OSError("denied"))
    assert run_push(s3, feed_of(cluster("a")), now=NOW, config=config(), sender=Recorder()) == "sent:1"
    assert "could not save the push state" in caplog.text


def test_an_unreadable_state_means_no_pushes() -> None:
    s3 = FakeS3(read_error=ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject"))
    with pytest.raises(ClientError):  # the handler wrapper turns this into a logged "failed"; sending blind could repeat stories
        run_push(s3, feed_of(cluster("a")), now=NOW, config=config(), sender=Recorder())


# ---- configuration from SSM


class FakeSsm:
    def __init__(self, values: dict[str, str], error: ClientError | None = None) -> None:
        self.values, self.error = values, error
        self.asked: list[str] = []

    def get_parameter(self, Name: str, WithDecryption: bool) -> dict[str, Any]:  # noqa: N803
        assert WithDecryption is True
        self.asked.append(Name)
        if self.error and Name not in self.values:
            raise self.error
        return {"Parameter": {"Value": self.values[Name]}}


def pem(key: ec.EllipticCurvePrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
    ).decode()


@pytest.fixture
def push_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUSH_KEY_PARAM", "/news/push/vapid-private-key")
    monkeypatch.setenv("PUSH_REG_PARAM", "/news/push/registration")
    monkeypatch.delenv("SITE_URL", raising=False)


def test_load_config_reads_the_sec1_pem_and_names_a_private_state_file(push_env: None) -> None:
    ssm = FakeSsm({"/news/push/vapid-private-key": pem(KEY), "/news/push/registration": registration()})
    loaded = push.load_config(ssm)
    assert loaded is not None and loaded.registration.site == "https://news.example.net"
    assert webpush.public_key_b64(loaded.key) == webpush.public_key_b64(KEY)
    assert loaded.state_name.startswith("push-") and len(loaded.state_name) == len("push-") + 64
    assert "BEGIN" not in loaded.state_name
    again = push.load_config(ssm)  # cached: no second read
    assert again is loaded and len(ssm.asked) == 2


def test_a_missing_registration_is_a_quiet_no_op(push_env: None, caplog: pytest.LogCaptureFixture) -> None:
    missing = ClientError({"Error": {"Code": "ParameterNotFound"}}, "GetParameter")
    ssm = FakeSsm({"/news/push/vapid-private-key": pem(KEY)}, error=missing)
    assert push.load_config(ssm) is None
    assert "ERROR" not in caplog.text and "WARNING" not in caplog.text


@pytest.mark.parametrize("unset", ["PUSH_KEY_PARAM", "PUSH_REG_PARAM"])
def test_not_configured_when_an_env_var_is_missing(push_env: None, monkeypatch: pytest.MonkeyPatch, unset: str) -> None:
    monkeypatch.delenv(unset)
    assert push.load_config(FakeSsm({})) is None


def test_the_site_can_come_from_the_environment_when_the_registration_has_none(
    push_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SITE_URL", "https://fallback.example.net")
    parsed = parse_registration(json.dumps({"v": 1, "subscription": SUBSCRIPTION}))
    assert parsed is not None and parsed.site == "https://fallback.example.net"


def test_invalid_key_or_registration_means_off(push_env: None) -> None:
    assert (
        push.load_config(FakeSsm({"/news/push/vapid-private-key": "garbage", "/news/push/registration": registration()})) is None
    )
    push.reset_config_cache()
    assert push.load_config(FakeSsm({"/news/push/vapid-private-key": pem(KEY), "/news/push/registration": "{}"})) is None


def test_other_ssm_errors_raise_on_first_read_and_keep_the_last_good_value_after(
    push_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    denied = ClientError({"Error": {"Code": "AccessDeniedException"}}, "GetParameter")
    with pytest.raises(ClientError):
        push.load_config(FakeSsm({}, error=denied))
    good = FakeSsm({"/news/push/vapid-private-key": pem(KEY), "/news/push/registration": registration()})
    first = push.load_config(good)
    assert first is not None
    clock = {"now": 0.0}
    monkeypatch.setattr(push.time, "monotonic", lambda: clock["now"])
    push.reset_config_cache()
    first = push.load_config(good)
    clock["now"] = push.CONFIG_TTL_SECONDS + 1
    assert push.load_config(FakeSsm({}, error=denied)) is first  # a failed refresh keeps the last good value


def test_ties_on_outlets_go_newest_first() -> None:
    feed = feed_of(
        cluster("old", sources=7, age_minutes=90),
        cluster("new", sources=7, age_minutes=5),
        cluster("most", sources=10, age_minutes=100),
    )
    assert titles(push.breaking(feed, reg(), {}, NOW)) == ["most", "new", "old"]


def test_a_naive_published_time_counts_as_utc_and_does_not_break_other_clusters() -> None:
    feed = feed_of(cluster("naive"), cluster("ok", sources=8))
    feed["clusters"][0]["published"] = (NOW - timedelta(minutes=20)).replace(tzinfo=None).isoformat()
    assert titles(push.breaking(feed, reg(), {}, NOW)) == ["ok", "naive"]


def test_newest_first_compares_instants_not_text() -> None:
    feed = feed_of(cluster("a", sources=7), cluster("b", sources=7))
    feed["clusters"][0]["published"] = (NOW - timedelta(minutes=50)).astimezone(ZoneInfo("America/Chicago")).isoformat()
    feed["clusters"][1]["published"] = (NOW - timedelta(minutes=10)).isoformat()
    assert titles(push.breaking(feed, reg(), {}, NOW)) == ["b", "a"]


@pytest.mark.parametrize("body", [b"[]", b'"text"', b"123", b'{"sent": [], "days": "x"}', b'{"sent": {"a": 5}}'])
def test_a_state_file_of_the_wrong_shape_is_an_empty_state(body: bytes) -> None:
    assert push.load_state(FakeS3({"data/push-x.json": body}), "push-x", NOW) == {"sent": {}, "days": {}}


def test_state_is_saved_after_each_message_so_a_dying_run_never_repeats_one() -> None:
    s3 = FakeS3()
    feed = feed_of(cluster("a", sources=9), cluster("b", sources=8))
    saved_before_each: list[int] = []

    def sender(subscription: dict[str, Any], message: dict[str, str], key: Any, site: str) -> int:
        saved_before_each.append(len(s3.puts))
        return 201

    run_push(s3, feed, now=NOW, config=config(), sender=sender)
    assert saved_before_each == [0, 1]  # the first message was already on disk when the second went out


def test_a_failure_logs_the_reason_without_secrets(caplog: pytest.LogCaptureFixture) -> None:
    sender = Recorder(webpush.PushError("push service answered 403"))
    run_push(FakeS3(), feed_of(cluster("a")), now=NOW, config=config(), sender=sender)
    assert "push service answered 403" in caplog.text


def test_not_set_up_is_rechecked_within_a_minute_but_a_good_config_is_kept(
    push_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"now": 100.0}
    monkeypatch.setattr(push.time, "monotonic", lambda: clock["now"])
    missing = ClientError({"Error": {"Code": "ParameterNotFound"}}, "GetParameter")
    assert push.load_config(FakeSsm({"/news/push/vapid-private-key": pem(KEY)}, error=missing)) is None
    clock["now"] += 61  # the phone was registered meanwhile
    good = FakeSsm({"/news/push/vapid-private-key": pem(KEY), "/news/push/registration": registration()})
    loaded = push.load_config(good)
    assert loaded is not None
    clock["now"] += 61
    assert push.load_config(FakeSsm({})) is loaded  # a good value is kept for ten minutes
