"""Runtime configuration. The location (home town, coordinates, nearby places, local feeds) is never in the repo:
it lives in one SSM Parameter Store parameter that is created by hand and read here at runtime."""

import functools
import hashlib
import json
import logging
import math
import os
import re
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()

LOCATION_PARAM_ENV = "LOCATION_PARAM"
SYMBOL = re.compile(r"[A-Za-z0-9^][A-Za-z0-9.^=_-]{0,14}")  # a quote symbol: starts with a letter, digit or ^, then . ^ = _ - too
MAX_TICKERS = 20
WATCH_KEY = re.compile(r"[a-z0-9]{16,64}")  # the unguessable part of the private watchlist file name
_REQUIRED = {"town": str, "lat": (int, float), "lon": (int, float), "nearby": list, "feeds": list}


def watch_name(key: str) -> str:
    """The quotes file name: a SHA-256 of the key, so a URL never contains the key that also guards the endpoint."""
    return f"watch-{hashlib.sha256(key.encode()).hexdigest()}"


@functools.cache
def finnhub_key() -> str:
    """The Finnhub API key, read once per container from the SecureString parameter named by FINNHUB_PARAM. It is never logged
    or put in a URL. Raises (KeyError, ClientError) when it is not configured: the earnings step then fails soft."""
    ssm = boto3.client("ssm")
    return str(ssm.get_parameter(Name=os.environ["FINNHUB_PARAM"], WithDecryption=True)["Parameter"]["Value"])


def earnings_name(key: str) -> str:
    """The earnings file name, from the same key as the quotes file (so it is private in the same way)."""
    return f"earn-{hashlib.sha256(key.encode()).hexdigest()}"


class ConfigError(Exception):
    """The location parameter is missing, not JSON, or lacks a required field."""


def parse_location(raw: str) -> dict[str, Any]:
    """Validate the parameter's JSON:
    {"town", "lat", "lon", "nearby": [...], "feeds": [...], optional "official": [...], optional "watch_key"}."""
    try:
        loc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError("location parameter is not valid JSON") from exc
    if not isinstance(loc, dict):
        raise ConfigError("location parameter must be a JSON object")
    for key, kind in _REQUIRED.items():
        if not isinstance(loc.get(key), kind) or isinstance(loc.get(key), bool):
            raise ConfigError(f"location parameter field {key!r} is missing or has the wrong type")
    official = loc.get("official", [])  # optional: a village's or school's own feeds, kept without the nearby-place check
    if not isinstance(official, list) or not all(isinstance(v, str) and v for v in loc["nearby"] + loc["feeds"] + official):
        raise ConfigError("location parameter fields 'nearby', 'feeds' and 'official' must be lists of non-empty strings")
    key = loc.get(
        "watch_key"
    )  # optional: the secret that guards the watchlist endpoint and names its quotes file; without it there is no watchlist
    if key is not None and not (isinstance(key, str) and WATCH_KEY.fullmatch(key)):
        raise ConfigError("location parameter field 'watch_key' must be 16 to 64 lowercase letters and digits")
    if not (math.isfinite(loc["lat"]) and -90 <= loc["lat"] <= 90 and math.isfinite(loc["lon"]) and -180 <= loc["lon"] <= 180):
        raise ConfigError("location parameter 'lat'/'lon' are out of range")
    return loc


def load_location(ssm: Any = None) -> dict[str, Any]:
    """Read and validate the location parameter named by the LOCATION_PARAM environment variable."""
    name = os.environ.get(LOCATION_PARAM_ENV)
    if not name:
        raise ConfigError(f"{LOCATION_PARAM_ENV} is not set")
    client = ssm or boto3.client("ssm")
    return parse_location(client.get_parameter(Name=name)["Parameter"]["Value"])


LOCAL_FEEDS_PARAM_ENV = "LOCAL_FEEDS_PARAM"


def _no_local_feeds() -> dict[str, list[str]]:
    return {"official": [], "alerts": []}  # a fresh one each time: callers may not share, or change, one another's lists


def parse_local_feeds(raw: str) -> dict[str, list[str]]:
    """The local feeds parameter's JSON: {"official": [...], "alerts": [...]}, both optional, each a list of non-empty strings."""
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError("local feeds parameter is not valid JSON") from exc
    if not isinstance(doc, dict):
        raise ConfigError("local feeds parameter must be a JSON object")
    out: dict[str, list[str]] = {}
    for key in ("official", "alerts"):
        urls = doc.get(key, [])
        if not isinstance(urls, list) or not all(isinstance(v, str) and v for v in urls):
            raise ConfigError(f"local feeds parameter field {key!r} must be a list of non-empty strings")
        out[key] = urls
    return out


def load_local_feeds(ssm: Any = None) -> dict[str, list[str]] | None:
    """The village's own feeds and alert feeds from the optional parameter named by LOCAL_FEEDS_PARAM. Never raises. A name that
    is not set or a parameter that does not exist means "none" (empty lists); a read or value that cannot be used is logged
    (never the value) and gives None, so the caller can keep the last good lists."""
    name = os.environ.get(LOCAL_FEEDS_PARAM_ENV)
    if not name:
        return _no_local_feeds()
    try:
        client = ssm or boto3.client("ssm")
        return parse_local_feeds(client.get_parameter(Name=name)["Parameter"]["Value"])
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ParameterNotFound":
            logger.info("no local feeds parameter; using none")
            return _no_local_feeds()
        logger.warning("could not read the local feeds parameter")
        return None
    except Exception:  # noqa: BLE001  (a bad value, a network error: the ingest runs without it)
        logger.warning("the local feeds parameter is unusable")
        return None


LOCATION_TTL_SECONDS = 600  # an edit to the parameter reaches a warm container within this long
_location: tuple[float, dict[str, Any]] | None = None


def reset_location_cache() -> None:
    global _location
    _location = None


def merged_local_feeds(location: dict[str, Any], extra: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """(official, alerts): `official` from the location parameter (kept for the first version of this feature) and from the
    local feeds parameter, each URL once, and `alerts` from the local feeds parameter. An alert feed is not also official."""
    alerts = list(dict.fromkeys(extra["alerts"]))
    official = [u for u in dict.fromkeys([*location.get("official", []), *extra["official"]]) if u not in alerts]
    return official, alerts


_local_feeds: tuple[float, dict[str, list[str]]] | None = None


def reset_local_feeds_cache() -> None:
    global _local_feeds
    _local_feeds = None


def cached_local_feeds() -> dict[str, list[str]]:
    """The local feeds, re-read at most every LOCATION_TTL_SECONDS. Never raises: a failed refresh keeps the last good lists, and
    a failed first read gives none (it is tried again on the next run, not cached)."""
    global _local_feeds
    now = time.monotonic()
    if _local_feeds is not None and now - _local_feeds[0] < LOCATION_TTL_SECONDS:
        return _local_feeds[1]
    loaded = load_local_feeds()
    if loaded is None:
        return _local_feeds[1] if _local_feeds is not None else _no_local_feeds()
    _local_feeds = (now, loaded)
    return loaded


def cached_location() -> dict[str, Any]:
    """The location, re-read at most every LOCATION_TTL_SECONDS (a warm Lambda container lives for hours, and the parameter is
    edited by hand). A failed refresh keeps the last good value; a failed first read raises and is not cached."""
    global _location
    now = time.monotonic()
    if _location is not None and now - _location[0] < LOCATION_TTL_SECONDS:
        return _location[1]
    try:
        loaded = load_location()
    except Exception:
        if _location is None:
            raise
        logger.warning("could not refresh the location parameter; using the last good value")
        return _location[1]
    _location = (now, loaded)
    return loaded
