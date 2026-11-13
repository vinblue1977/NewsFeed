"""Runtime configuration. The location (home town, coordinates, nearby places, local feeds) is never in the repo:
it lives in one SSM Parameter Store parameter that is created by hand and read here at runtime."""

import json
import os
from typing import Any

import boto3

LOCATION_PARAM_ENV = "LOCATION_PARAM"
_REQUIRED = {"town": str, "lat": (int, float), "lon": (int, float), "nearby": list, "feeds": list}


class ConfigError(Exception):
    """The location parameter is missing, not JSON, or lacks a required field."""


def parse_location(raw: str) -> dict[str, Any]:
    """Validate the parameter's JSON: {"town", "lat", "lon", "nearby": [...], "feeds": [...]}."""
    try:
        loc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError("location parameter is not valid JSON") from exc
    if not isinstance(loc, dict):
        raise ConfigError("location parameter must be a JSON object")
    for key, kind in _REQUIRED.items():
        if not isinstance(loc.get(key), kind) or isinstance(loc.get(key), bool):
            raise ConfigError(f"location parameter field {key!r} is missing or has the wrong type")
    return loc


def load_location(ssm: Any = None) -> dict[str, Any]:
    """Read and validate the location parameter named by the LOCATION_PARAM environment variable."""
    name = os.environ.get(LOCATION_PARAM_ENV)
    if not name:
        raise ConfigError(f"{LOCATION_PARAM_ENV} is not set")
    client = ssm or boto3.client("ssm")
    return parse_location(client.get_parameter(Name=name)["Parameter"]["Value"])
