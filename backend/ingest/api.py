"""The one endpoint (Lambda Function URL behind CloudFront at /api/watchlist): read or replace the private watchlist.

POST {"key": "<watch key>"} returns the saved symbols; add "symbols": [...] to replace them. The key is checked in constant
time against the one in the location parameter. Nothing here is logged except the outcome."""

import base64
import hmac
import json
import logging
import os
from typing import Any

import boto3

from ingest.config import cached_location
from ingest.watchlist import WatchlistError, normalize, read_watchlist, write_watchlist

logger = logging.getLogger()
MAX_BODY = 2048


def _reply(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(body),
    }


def _body(event: dict[str, Any]) -> str:
    raw = event.get("body") or ""
    return base64.b64decode(raw).decode() if event.get("isBase64Encoded") else raw


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    if event.get("requestContext", {}).get("http", {}).get("method") != "POST":
        return _reply(405, {"error": "POST only"})
    try:
        text = _body(event)
        if len(text) > MAX_BODY:
            return _reply(413, {"error": "too large"})
        data = json.loads(text)
        key, symbols = data["key"], data.get("symbols")
    except ValueError, KeyError, TypeError:
        return _reply(400, {"error": "bad request"})
    expected = cached_location().get("watch_key")
    if not expected or not isinstance(key, str) or not hmac.compare_digest(key.encode(), expected.encode()):
        return _reply(403, {"error": "forbidden"})
    s3 = boto3.client("s3")
    if symbols is None:
        try:
            return _reply(200, {"symbols": read_watchlist(s3)})
        except Exception:  # noqa: BLE001  (an S3 error must not look like an empty list)
            logger.exception("could not read the watchlist")
            return _reply(502, {"error": "storage unavailable"})
    try:
        saved = normalize(symbols)
    except WatchlistError as exc:
        return _reply(400, {"error": str(exc)})
    try:
        write_watchlist(s3, saved)
    except Exception:  # noqa: BLE001
        logger.exception("could not save the watchlist")
        return _reply(502, {"error": "storage unavailable"})
    try:  # refresh the quotes now; the saved list is what counts, so a failure here is only logged
        boto3.client("lambda").invoke(
            FunctionName=os.environ["INGEST_FUNCTION"],
            InvocationType="Event",
            Payload=json.dumps({"only": "markets", "force": True}).encode(),
        )
    except Exception:  # noqa: BLE001
        logger.warning("could not start a quote refresh", exc_info=True)
    return _reply(200, {"symbols": saved})
