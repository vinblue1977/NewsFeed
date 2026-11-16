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
    """Validate the parameter's JSON: {"town", "lat", "lon", "nearby": [...], "feeds": [...], optional "watch_key"}."""
    try:
        loc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError("location parameter is not valid JSON") from exc
    if not isinstance(loc, dict):
        raise ConfigError("location parameter must be a JSON object")
    for key, kind in _REQUIRED.items():
        if not isinstance(loc.get(key), kind) or isinstance(loc.get(key), bool):
            raise ConfigError(f"location parameter field {key!r} is missing or has the wrong type")
    if not all(isinstance(v, str) and v for v in loc["nearby"] + loc["feeds"]):
        raise ConfigError("location parameter fields 'nearby' and 'feeds' must be lists of non-empty strings")
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


LOCATION_TTL_SECONDS = 600  # an edit to the parameter reaches a warm container within this long
_location: tuple[float, dict[str, Any]] | None = None


def reset_location_cache() -> None:
    global _location
    _location = None


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
