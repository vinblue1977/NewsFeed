"""Push notifications for breaking stories, sent from the ingest Lambda after the feed is written.

One user, one phone. The phone's Web Push subscription, the app's own origin (`site`, the VAPID `sub` claim) and the
notification preferences live in the SecureString parameter named by PUSH_REG_PARAM (registered by hand, never in the repo);
the VAPID private key (a PEM) is in the one named by PUSH_KEY_PARAM.
Nothing is sent if either is missing or invalid. A failure here is logged and never touches the feed.

Which stories qualify (strict on purpose, so a push means something):
  - six or more distinct outlets in one cluster, newest article under two hours old, topic switched on; or
  - a lead headline that starts with BREAKING / Developing / LIVE from an outlet on the trusted list, same age and topic rules.
Quiet hours hold pushes back (they are not marked sent, so a still-fresh story can go out afterwards). At most 2 pushes per run
and 5 per local day, and one cluster is pushed once: the sent ids are kept in a private state file, pruned after 3 days.

Village alerts are the other kind: every item from a feed listed under `alerts` in the location parameter, under two days old and
not yet sent, when the registration has `alerts` on (the default). They go before breaking stories, are sent through quiet hours
(an alert feed is rare and official), and share the per-run and per-day caps. Their sent ids start with "alert:"."""

import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import boto3
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.asymmetric import ec

from ingest import webpush
from ingest.articles import dumps

logger = logging.getLogger()

TOPICS = frozenset({"us", "world", "india", "sports", "tech", "business", "local"})
MIN_SOURCES = 6
MAX_AGE = timedelta(hours=2)
ALERT_MAX_AGE = timedelta(days=2)  # an official alert feed is quiet: an item a day old is still news
PER_RUN = 2
PER_DAY = 5
KEEP = timedelta(days=3)
DEFAULT_QUIET = (22 * 60, 7 * 60)  # 22:00 to 07:00, when the registration says nothing
CONFIG_TTL_SECONDS = 600  # an edit to the parameters reaches a warm container within this long
NEGATIVE_TTL_SECONDS = 60  # "not set up" is re-checked sooner, so registering the phone takes effect within a minute
TRUSTED = frozenset({"BBC News", "NPR", "PBS NewsHour", "CBS News", "ABC News", "NBC News", "The Guardian", "Al Jazeera", "DW"})
BREAKING = re.compile(r"\s*(?:breaking(?:\s+news)?|developing|live)\s*[:|–—-]", re.IGNORECASE)
TITLE_CHARS = 140
BODY_CHARS = 100


@dataclass(frozen=True)
class Registration:
    """The phone's subscription and what it asked for."""

    subscription: dict[str, Any]  # {"endpoint", "keys": {"p256dh", "auth"}}
    topics: frozenset[str]
    weather: bool  # reserved: weather alert pushes are a later change
    quiet: tuple[int, int] | None  # minutes after local midnight: (start, end), end may be before start
    tz: ZoneInfo
    site: str  # https://<the app's origin>: the VAPID `sub` claim (the deploy cannot know it: see parse_registration)
    alerts: bool = True  # push the village alert feeds (a registration made before this existed gets them)


@dataclass(frozen=True)
class Notification:
    """One message to send. `kind` lets other producers (weather alerts, later) share the caps, quiet hours and state."""

    kind: str
    id: str  # the dedupe key: a cluster id for breaking stories
    title: str
    body: str
    url: str
    topic: str

    def payload(self) -> dict[str, str]:
        return {"title": self.title, "body": self.body, "url": self.url, "tag": self.id}


def _minutes(text: Any) -> int | None:
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", text) if isinstance(text, str) else None
    return int(match[1]) * 60 + int(match[2]) if match else None


def parse_registration(raw: str) -> Registration | None:
    """The registration parameter's JSON, checked. None (with one log line, never the value) if it is not usable."""
    try:
        doc = json.loads(raw)
        sub = doc["subscription"]
        endpoint, keys = sub["endpoint"], sub["keys"]
        if (
            doc.get("v") != 1
            or not isinstance(endpoint, str)
            or not isinstance(keys["p256dh"], str)
            or not isinstance(keys["auth"], str)
        ):
            raise ValueError("shape")
        webpush.check_endpoint(endpoint)
        site = doc.get("site", os.environ.get("SITE_URL", ""))  # the app writes its own origin; SITE_URL is an optional fallback
        if not (isinstance(site, str) and site.startswith("https://") and len(site) > len("https://")):
            raise ValueError("site")
        prefs = doc.get("prefs") or {}
        topics = prefs.get("topics", ["us", "world", "india", "sports", "local"])
        if not isinstance(topics, list):
            raise ValueError("topics")
        quiet: tuple[int, int] | None = DEFAULT_QUIET
        if "quiet" in prefs:
            q = prefs["quiet"]
            if q is None:
                quiet = None  # no quiet hours asked for
            elif isinstance(q, dict) and _minutes(q.get("start")) is not None and _minutes(q.get("end")) is not None:
                quiet = (_minutes(q["start"]) or 0, _minutes(q["end"]) or 0)
        return Registration(
            subscription={"endpoint": endpoint, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]}},
            topics=frozenset(t for t in topics if t in TOPICS),
            weather=prefs.get("weather") is True,
            quiet=quiet,
            tz=ZoneInfo(str(prefs.get("tz", "UTC"))),
            site=site.rstrip("/"),
            alerts=prefs.get("alerts") is not False,
        )
    except Exception:  # noqa: BLE001  (bad JSON, a missing field, an unknown time zone: all mean "not registered")
        logger.warning("push registration is missing or invalid; no notifications are sent")
        return None


def _when(text: Any) -> datetime | None:
    """An ISO time as an aware datetime (no offset means UTC), or None if it is not one."""
    try:
        when = datetime.fromisoformat(text)
    except TypeError, ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def in_quiet(now: datetime, reg: Registration) -> bool:
    """Whether `now` falls inside the quiet hours, in the registration's time zone (a window may cross midnight)."""
    if reg.quiet is None:
        return False
    start, end = reg.quiet
    local = now.astimezone(reg.tz)
    minute = local.hour * 60 + local.minute
    if start == end:
        return False
    return start <= minute < end if start < end else minute >= start or minute < end


def local_day(now: datetime, reg: Registration) -> str:
    return now.astimezone(reg.tz).strftime("%Y-%m-%d")


def breaking(feed: dict[str, Any], reg: Registration, sent: dict[str, Any], now: datetime) -> list[Notification]:
    """The clusters that qualify, most outlets first (then newest). Already-sent ones are left out."""
    items = {i["id"]: i for i in feed.get("items", [])}
    found: list[tuple[int, datetime, Notification]] = []
    for cluster in feed.get("clusters", []):
        if cluster["id"] in sent or cluster["topic"] not in reg.topics:
            continue
        published = _when(cluster["published"])
        if published is None or now - published >= MAX_AGE:
            continue
        lead = items.get(cluster["lead"], {})
        source = str(lead.get("source", ""))
        title = str(cluster["title"])
        if not (cluster["sources"] >= MIN_SOURCES or (source in TRUSTED and BREAKING.match(title))):
            continue
        many = cluster["sources"] > 1
        found.append(
            (
                cluster["sources"],
                published,
                Notification(
                    kind="breaking",
                    id=cluster["id"],
                    title=title[:TITLE_CHARS],
                    body=(f"{cluster['sources']} outlets \u00b7 {source}" if many else source)[:BODY_CHARS],
                    url=f"/#/story/{cluster['id']}" if many else f"/#/read/{cluster['lead']}",
                    topic=cluster["topic"],
                ),
            )
        )
    found.sort(key=lambda f: f[1], reverse=True)  # newest first (by the instant, whatever the offset)...
    found.sort(key=lambda f: -f[0])  # ...then most outlets first (the sort is stable)
    return [n for _, _, n in found]


def village_alerts(
    feed: dict[str, Any], reg: Registration, sent: dict[str, Any], now: datetime, alert_ids: Iterable[str]
) -> list[Notification]:
    """The items from the alert feeds (`alert_ids`) that are under ALERT_MAX_AGE old and not yet sent, newest first."""
    if not reg.alerts:
        return []
    wanted = set(alert_ids)
    found: list[tuple[datetime, Notification]] = []
    for item in feed.get("items", []):
        key = f"alert:{item.get('id')}"
        if item.get("id") not in wanted or key in sent:
            continue
        published = _when(item.get("published"))
        if published is None or now - published >= ALERT_MAX_AGE:
            continue
        found.append(
            (
                published,
                Notification(
                    kind="alert",
                    id=key,
                    title=str(item.get("title", ""))[:TITLE_CHARS],
                    body=str(item.get("source", ""))[:BODY_CHARS],
                    url=f"/#/read/{item['id']}",
                    topic="local",
                ),
            )
        )
    found.sort(key=lambda f: f[0], reverse=True)
    return [n for _, n in found]


def candidates(
    feed: dict[str, Any],
    reg: Registration,
    sent: dict[str, Any],
    now: datetime,
    alert_ids: Iterable[str] = (),
    quiet: bool = False,
) -> list[Notification]:
    """Everything that could be pushed now: village alerts first, then breaking stories unless it is quiet (alerts go through
    quiet hours). Weather alerts (a later change) add their own Notification here when reg.weather is on; the caps, dedupe and
    state below then apply to them unchanged."""
    return [*village_alerts(feed, reg, sent, now, alert_ids), *([] if quiet else breaking(feed, reg, sent, now))]


@dataclass(frozen=True)
class Config:
    registration: Registration
    key: ec.EllipticCurvePrivateKey
    state_name: str  # data/<state_name>.json, a hash of the private key: not guessable


_config: tuple[float, Config | None] | None = None


def reset_config_cache() -> None:
    global _config
    _config = None


def _configured() -> bool:
    """Whether the deploy set the two parameter names."""
    return bool(os.environ.get("PUSH_KEY_PARAM") and os.environ.get("PUSH_REG_PARAM"))


def _read_config(ssm: Any) -> Config | None:
    try:
        raw_key = str(ssm.get_parameter(Name=os.environ["PUSH_KEY_PARAM"], WithDecryption=True)["Parameter"]["Value"])
        raw_reg = str(ssm.get_parameter(Name=os.environ["PUSH_REG_PARAM"], WithDecryption=True)["Parameter"]["Value"])
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ParameterNotFound":
            raise
        logger.info("push is not set up (parameter not found)")
        return None
    registration = parse_registration(raw_reg)
    if registration is None:
        return None
    try:
        key = webpush.load_vapid_key(raw_key)
    except webpush.PushError:
        logger.warning("the VAPID private key is not valid; no notifications are sent")
        return None
    return Config(registration, key, "push-" + hashlib.sha256(("push:" + raw_key.strip()).encode()).hexdigest())


def load_config(ssm: Any = None) -> Config | None:
    """The push configuration, read at most every CONFIG_TTL_SECONDS (None when not set up or not valid). A failed re-read keeps
    the last good value; a failed first read raises (the caller logs it, and the feed is unaffected)."""
    global _config
    if not _configured():
        logger.info("push is not configured")
        return None
    now = time.monotonic()
    if _config is not None and now - _config[0] < (CONFIG_TTL_SECONDS if _config[1] is not None else NEGATIVE_TTL_SECONDS):
        return _config[1]
    try:
        config = _read_config(ssm or boto3.client("ssm"))
    except Exception:
        if _config is None:
            raise
        logger.warning("could not refresh the push parameters; using the last good value")
        return _config[1]
    _config = (now, config)
    return config


def load_state(s3: Any, name: str, now: datetime) -> dict[str, Any]:
    """{"sent": {cluster id: iso time}, "days": {local day: count}}, with entries older than KEEP dropped. A missing file is an
    empty state; any other read error is raised, so a storage hiccup never turns into the same story pushed again."""
    try:
        body = s3.get_object(Bucket=os.environ["DATA_BUCKET"], Key=f"{os.environ['DATA_PREFIX']}/{name}.json")["Body"].read()
        doc = json.loads(body)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in ("NoSuchKey", "404"):
            raise
        doc = {}
    except ValueError:
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    cutoff = now - KEEP
    sent_raw, days_raw = doc.get("sent"), doc.get("days")
    sent = {}
    for cid, at in (sent_raw if isinstance(sent_raw, dict) else {}).items():
        when = _when(at)
        if when is not None and when >= cutoff:
            sent[cid] = at
    oldest_day = cutoff.date().isoformat()
    days = {d: n for d, n in (days_raw if isinstance(days_raw, dict) else {}).items() if isinstance(n, int) and d >= oldest_day}
    state: dict[str, Any] = {"sent": sent, "days": days}
    if isinstance(doc.get("seeded"), str):
        state["seeded"] = doc["seeded"]  # when the alert feeds were first seen (see run_push); never pruned
    return state


def save_state(s3: Any, name: str, state: dict[str, Any], now: datetime) -> None:
    s3.put_object(
        Bucket=os.environ["DATA_BUCKET"],
        Key=f"{os.environ['DATA_PREFIX']}/{name}.json",
        Body=dumps({"generated": now.isoformat(timespec="seconds"), **state}),
        ContentType="application/json",
    )


def run_push(
    s3: Any,
    feed: dict[str, Any],
    alert_ids: Iterable[str] = (),
    *,
    now: datetime | None = None,
    config: Config | None = None,
    sender: Callable[..., int] = webpush.send,
) -> str:
    """Send what qualifies. Returns a short status for the run's result: off, quiet, none, sent:N, expired or failed.
    `alert_ids` are the feed items that came from the village alert feeds."""
    now = now or datetime.now(UTC)
    config = config or load_config()
    if config is None:
        return "off"
    reg = config.registration
    alert_ids = set(alert_ids)
    quiet = in_quiet(now, reg)
    if quiet and not (alert_ids and reg.alerts):
        return "quiet"
    state = load_state(s3, config.state_name, now)
    if alert_ids and reg.alerts and "seeded" not in state:
        # The first run that sees the alert feeds: what they already hold is old news, not a burst of alerts (some at night).
        # Mark it sent without pushing; only items that appear from now on are pushed.
        for note in village_alerts(feed, reg, state["sent"], now, alert_ids):
            state["sent"][note.id] = now.isoformat(timespec="seconds")
        state["seeded"] = now.isoformat(timespec="seconds")
        try:
            save_state(s3, config.state_name, state, now)
        except Exception:  # noqa: BLE001
            logger.exception("could not save the push state; the existing alerts may be pushed")
    day = local_day(now, reg)
    room = min(PER_RUN, PER_DAY - state["days"].get(day, 0))
    todo = candidates(feed, reg, state["sent"], now, alert_ids, quiet)[: max(room, 0)]
    status = "quiet" if quiet else "none"
    count = 0
    for note in todo:
        try:
            sender(reg.subscription, note.payload(), config.key, reg.site)
        except webpush.Expired:
            logger.error("push subscription expired (the push service answered 404 or 410): register the phone again")
            status = "expired"
            break
        except Exception as exc:  # noqa: BLE001  (a bad key, a network failure, a rejection: stop, never raise)
            reason = exc if isinstance(exc, webpush.PushError) else type(exc).__name__  # PushError texts never hold secrets
            logger.warning("push failed (%s); stopping for this run", reason)
            status = "failed"
            break
        state["sent"][note.id] = now.isoformat(timespec="seconds")
        state["days"][day] = state["days"].get(day, 0) + 1
        count += 1
        status = f"sent:{count}"
        try:  # after each message, so a run that dies mid-way never repeats one that already went
            save_state(s3, config.state_name, state, now)
        except Exception:  # noqa: BLE001
            logger.exception("could not save the push state; the same stories may be pushed again next run")
    return status


def send_test(
    *,
    config: Config | None = None,
    sender: Callable[..., int] = webpush.send,
) -> str:
    """One fixed test message, for checking the whole path by hand (invoke the Lambda with {"only": "push-test"}). Ignores
    quiet hours, the caps and the dedupe state on purpose, and records nothing. Returns off, sent, expired or failed."""
    config = config or load_config()
    if config is None:
        return "off"
    reg = config.registration
    tag = f"push-test-{int(datetime.now(UTC).timestamp())}"  # unique, so a second test is not folded into the first
    note = {"title": "Test notification", "body": "Push is working.", "url": "/", "tag": tag}
    try:
        sender(reg.subscription, note, config.key, reg.site)
    except webpush.Expired:
        logger.error("push subscription expired (the push service answered 404 or 410): register the phone again")
        return "expired"
    except Exception as exc:  # noqa: BLE001
        reason = exc if isinstance(exc, webpush.PushError) else type(exc).__name__
        logger.warning("push test failed (%s)", reason)
        return "failed"
    return "sent"
