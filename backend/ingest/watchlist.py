"""The private watchlist: the symbols live in one S3 object that CloudFront never serves (it only serves data/*)."""

import json
import os
from typing import Any

from botocore.exceptions import ClientError

from ingest.config import MAX_TICKERS, SYMBOL


class WatchlistError(Exception):
    """The symbols are not a valid list."""


def normalize(symbols: Any) -> list[str]:
    """Upper-cased, de-duplicated symbols in order. Raises WatchlistError if not a list of at most MAX_TICKERS quote symbols."""
    if not isinstance(symbols, list) or not all(isinstance(s, str) and SYMBOL.fullmatch(s.strip()) for s in symbols):
        raise WatchlistError("symbols must be a list of quote symbols")
    unique = list(dict.fromkeys(s.strip().upper() for s in symbols))
    if len(unique) > MAX_TICKERS:
        raise WatchlistError(f"at most {MAX_TICKERS} symbols")
    return unique


def read_watchlist(s3: Any) -> list[str]:
    """The saved symbols; empty if there is no list yet or the file is corrupt. Any other S3 error (access denied,
    throttling, an outage) is raised, so a hiccup is never mistaken for an empty list."""
    try:
        body = s3.get_object(Bucket=os.environ["DATA_BUCKET"], Key=os.environ["WATCHLIST_KEY"])["Body"].read()
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return []
        raise
    try:
        return normalize(json.loads(body)["symbols"])
    except ValueError, KeyError, TypeError, WatchlistError:
        return []


def write_watchlist(s3: Any, symbols: list[str]) -> None:
    s3.put_object(
        Bucket=os.environ["DATA_BUCKET"],
        Key=os.environ["WATCHLIST_KEY"],
        Body=json.dumps({"symbols": symbols}).encode(),
        ContentType="application/json",
    )
