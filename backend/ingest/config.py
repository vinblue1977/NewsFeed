"""Runtime configuration. The location (home town, coordinates, nearby places, local feeds) is never in the repo:
it lives in one SSM Parameter Store parameter that is created by hand and read here at runtime."""

import functools
import json
import math
import os
import re
from typing import Any

import boto3

LOCATION_PARAM_ENV = "LOCATION_PARAM"
SYMBOL = re.compile(r"[A-Za-z0-9^][A-Za-z0-9.^=_-]{0,14}")  # a quote symbol: starts with a letter, digit or ^, then . ^ = _ - too
MAX_TICKERS = 20
_REQUIRED = {"town": str, "lat": (int, float), "lon": (int, float), "nearby": list, "feeds": list}


class ConfigError(Exception):
    """The location parameter is missing, not JSON, or lacks a required field."""


def parse_location(raw: str) -> dict[str, Any]:
    """Validate the parameter's JSON: {"town", "lat", "lon", "nearby": [...], "feeds": [...], optional "tickers": [...]}."""
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
    tickers = loc.get("tickers", [])  # optional: extra quote symbols for the Markets tab
    if (
        not isinstance(tickers, list)
        or len(tickers) > MAX_TICKERS
        or not all(isinstance(t, str) and SYMBOL.fullmatch(t) for t in tickers)
    ):
        raise ConfigError(f"location parameter field 'tickers' must be a list of at most {MAX_TICKERS} quote symbols")
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


@functools.cache
def cached_location() -> dict[str, Any]:
    """The location, read once per Lambda container (a failure is not cached, so a fixed parameter is picked up)."""
    return load_location()
